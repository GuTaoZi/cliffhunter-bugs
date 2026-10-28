// SERVER-107471 reproduction, run as an O3 order permutation.
//
// ONE query shape -- verified, not assumed -- with two variants that differ only in
// whether .skip(S) is present, and two parameter classes:
//
//   P  ("paginated")  find({indexField1:7, indexField10:0}, proj).skip(S).limit(10)
//                     19 000 matches. The multi-planner picks IXSCAN{indexField1}
//                     because the SKIP stage eats results but not work units.
//   R  ("rare")       find({indexField1:7, indexField10:93333+k}, proj).limit(10)
//                     1 match. Wants IXSCAN{indexField10} -- 1 key. Under P's plan it
//                     reads 20 000 documents, i.e. 20 000x.
//
// S1_SKIP=0 turns P into the no-skip control: the ONLY change is deleting .skip(S) from
// one of the two variants, holding the multiset, the data and the filters fixed. That is
// what isolates skip as the causal variable rather than the parameter value.
//
// Instrumentation is the database PROFILER, not explain(). explain() re-runs the
// multi-planner and would hide the cached-plan behaviour entirely -- this project has
// fallen into that trap once already (docs/oracle-o3.md, pitfall list).
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('S1_DB', 'ch_s107471');
const COLL   = CH.env('S1_COLL', 'docs');
const F1_HOT = CH.envInt('S1_F1_HOT', 7);
const RARE_B = CH.envInt('S1_RARE_BASE', 93333);
const N_RARE = CH.envInt('S1_N_RARE', 1000);
const SKIP   = CH.envInt('S1_SKIP', 5000);     // 0 => the no-skip control arm
const LIMIT  = CH.envInt('S1_LIMIT', 10);
const NP     = CH.envInt('S1_NP', 4);          // P queries per epoch
const NR     = CH.envInt('S1_NR', 8);          // R queries per epoch
const EPOCHS = CH.envInt('S1_EPOCHS', 3);
const ORDERS = CH.env('S1_ORDERS', 'P_first,R_first,alternating,shuffled').split(',');
const FW     = CH.env('S1_FRAMEWORK', 'trySbeRestricted');
const QUIET  = CH.envInt('S1_QUIET', 0) === 1; // drop profiler + per-query polling (cost runs)
const LABEL  = CH.env('S1_LABEL', SKIP > 0 ? 'skip' + SKIP : 'noskip');
const REP    = CH.envInt('S1_REP', 0);       // repeat index; the report aggregates over these
const KIND   = CH.env('S1_KIND', 's107471_order');  // 's107471_sweep' for the skip sweep

const d = db.getSiblingDB(DB);
const coll = d.getCollection(COLL);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });

const PROJ = { indexField1: 1, indexField10: 1, _id: 0 };
const pFilter = { indexField1: F1_HOT, indexField10: 0 };
const rFilter = (k) => ({ indexField1: F1_HOT, indexField10: RARE_B + (k % N_RARE) });

function runQuery(cls, k) {
  let cur = coll.find(cls === 'P' ? pFilter : rFilter(k), PROJ);
  if (cls === 'P' && SKIP > 0) cur = cur.skip(SKIP);
  return cur.limit(LIMIT).toArray();
}

// --- pitfall 3 of docs/oracle-o3.md: the same-shape premise is VERIFIED, not assumed ----
// This is also the whole premise of SERVER-107471, so it is reported as a result.
function keyOf(cur) { const e = cur.explain(); return { key: e.queryPlanner.planCacheKey, hash: e.queryPlanner.queryHash }; }
const premise = {
  P_noskip: keyOf(coll.find(pFilter, PROJ).limit(LIMIT)),
  P_skip:   keyOf(coll.find(pFilter, PROJ).skip(SKIP || 5000).limit(LIMIT)),
  R_noskip: keyOf(coll.find(rFilter(0), PROJ).limit(LIMIT)),
  R_skip:   keyOf(coll.find(rFilter(0), PROJ).skip(SKIP || 5000).limit(LIMIT)),
};
premise.all_same_key  = new Set(Object.values(premise).filter((v) => v && v.key).map((v) => v.key)).size === 1;
premise.all_same_hash = new Set(Object.values(premise).filter((v) => v && v.hash).map((v) => v.hash)).size === 1;

// --- the multiset, and the orders it can arrive in --------------------------------------
function epochOrder(name) {
  const P = Array(NP).fill('P'), R = Array(NR).fill('R');
  switch (name) {
    // The two orders the ticket's "Expected Behavior" contrasts: the cache entry created
    // by the skip+limit query, versus the one created by the limit-only query.
    case 'P_first':     return P.concat(R);
    case 'R_first':     return R.concat(P);
    case 'alternating': { const o = []; const step = Math.max(1, Math.round(NR / NP));
                          for (let i = 0; i < NP; i++) { o.push('P'); for (let j = 0; j < step; j++) o.push('R'); }
                          while (o.filter((x) => x === 'R').length > NR) o.splice(o.lastIndexOf('R'), 1);
                          while (o.filter((x) => x === 'R').length < NR) o.push('R');
                          return o; }
    case 'shuffled': {
      const o = P.concat(R);
      let s = 987654321;                        // fixed seed: the permutation is reproducible
      for (let i = o.length - 1; i > 0; i--) {
        s = (s * 1103515245 + 12345) & 0x7fffffff;
        const j = s % (i + 1);
        [o[i], o[j]] = [o[j], o[i]];
      }
      return o;
    }
    default: throw new Error('unknown order ' + name);
  }
}

// --- observation helpers ----------------------------------------------------------------
function cacheState() {
  const e = coll.aggregate([{ $planCacheStats: {} }]).toArray();
  if (e.length === 0) return { present: false };
  const x = e[0];
  const works = x.works && x.works.low !== undefined ? x.works.low : x.works;
  const idx = JSON.stringify(x.cachedPlan || {}).match(/"indexName":"(\w+)"/);
  return { present: true, isActive: x.isActive, works: works,
           plan: idx ? idx[1] : '?', key: x.planCacheKey };
}

function counters() {
  const ss = db.serverStatus();
  const n = (v) => (v && v.low !== undefined ? v.low : v);
  const c = ss.metrics.query.planCache.classic;
  const qe = ss.metrics.queryExecutor;
  // metrics.query.multiPlanner.classicMicros is the instrument W5 wished it had: optimizer
  // CPU, server-side, in microseconds. A replan re-enters multi-planning, so this counts
  // the work a replan throws away -- which no per-operation work counter contains.
  const mp = ss.metrics.query.multiPlanner;
  return { hits: n(c.hits), misses: n(c.misses), skipped: n(c.skipped),
           replanned: n(c.replanned),
           replanned_plan_is_cached_plan: n(c.replanned_plan_is_cached_plan),
           evicted: n(c.cached_plans_evicted),
           inactive_replaced: n(c.inactive_cached_plans_replaced),
           executor_scanned_keys: n(qe.scanned), executor_scanned_docs: n(qe.scannedObjects),
           mp_count: n(mp.classicCount), mp_micros: n(mp.classicMicros),
           mp_works: n(mp.classicWorks) };
}

function resetProfiler() {
  if (QUIET) return;
  d.setProfilingLevel(0);
  d.system.profile.drop();
  d.createCollection('system.profile', { capped: true, size: 64 * 1024 * 1024 });
  d.setProfilingLevel(2);
}

// --- the run ------------------------------------------------------------------------------
let valueCursor = 0;
for (const orderName of ORDERS) {
  coll.getPlanCache().clear();
  resetProfiler();
  const c0 = counters();
  const trace = [];

  for (let epoch = 0; epoch < EPOCHS; epoch++) {
    for (const cls of epochOrder(orderName)) {
      const k = valueCursor++;
      const before = QUIET ? null : cacheState();
      const ns = CH.timeNs(() => runQuery(cls, k));
      const after = QUIET ? null : cacheState();
      trace.push({ epoch: epoch, cls: cls, k: k % N_RARE, wall_ms: ns / 1e6,
                   cache_before: before, cache_after: after });
    }
  }

  if (!QUIET) d.setProfilingLevel(0);
  const prof = QUIET ? [] : d.system.profile.find({ op: 'query', ns: DB + '.' + COLL })
                .sort({ ts: 1 }).toArray();
  for (let i = 0; i < trace.length && i < prof.length; i++) {
    const p = prof[i];
    trace[i].docsExamined = p.docsExamined;
    trace[i].keysExamined = p.keysExamined;
    trace[i].nreturned = p.nreturned;
    trace[i].millis = p.millis;
    trace[i].planSummary = p.planSummary;
    trace[i].fromPlanCache = p.fromPlanCache === true;
    trace[i].fromMultiPlanner = p.fromMultiPlanner === true;
    trace[i].replanned = p.replanned === true;
    trace[i].replanReason = p.replanReason || null;
  }

  const c1 = counters();
  const delta = {};
  for (const k of Object.keys(c1)) delta[k] = c1[k] - c0[k];

  const lastEpoch = trace.filter((t) => t.epoch === EPOCHS - 1);
  const sum = (rows, f) => rows.reduce((a, r) => a + (f(r) || 0), 0);
  CH.emit({
    kind: KIND, coll: COLL, arm: LABEL, skip: SKIP, order: orderName, rep: REP,
    np: NP, nr: NR, epochs: EPOCHS, n_queries: trace.length, premise: premise,
    total_docs_examined: sum(trace, (r) => r.docsExamined),
    total_keys_examined: sum(trace, (r) => r.keysExamined),
    total_millis: sum(trace, (r) => r.millis),
    total_wall_ms: sum(trace, (r) => r.wall_ms),
    last_epoch_docs_examined: sum(lastEpoch, (r) => r.docsExamined),
    last_epoch_millis: sum(lastEpoch, (r) => r.millis),
    n_catastrophic: trace.filter((r) => (r.docsExamined || 0) > 1000).length,
    by_class: ['P', 'R'].reduce((acc, k) => {
      const rows = trace.filter((r) => r.cls === k);
      if (rows.length) {
        acc[k] = { n: rows.length, docs: sum(rows, (r) => r.docsExamined),
                   keys: sum(rows, (r) => r.keysExamined),
                   millis: sum(rows, (r) => r.millis),
                   max_docs: Math.max.apply(null, rows.map((r) => r.docsExamined || 0)),
                   replans: rows.filter((r) => r.replanned).length,
                   plans: rows.reduce((a, r) => { const p = r.planSummary || '?'; a[p] = (a[p] || 0) + 1; return a; }, {}) };
      }
      return acc;
    }, {}),
    final_cache: cacheState(), counters: delta, trace: QUIET ? [] : trace,
  });
  print('arm ' + LABEL + ' order ' + orderName + ': done (' + trace.length + ' queries, '
        + trace.filter((r) => (r.docsExamined || 0) > 1000).length + ' catastrophic)');
}

if (!QUIET) d.setProfilingLevel(0);

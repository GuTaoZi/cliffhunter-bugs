// SERVER-79039 reproduction, run as an O3 order permutation.
//
// ONE query shape, find({a:<int>, b:0}), two parameter classes that want the SAME plan:
//   C ("cheap")      5 results,  IXSCAN{a} reaches EOF at ~6 works
//   E ("expensive")  3 results,  IXSCAN{a} reaches EOF at ~N_E works
// Neither is mis-planned. The only thing that differs is how much work the same plan
// costs, and that is exactly the variable the plan cache stores and mis-updates.
//
// The reported cycle, which the per-query state trace below makes visible directly:
//   C -> entry ACTIVE, works = 6, replan bar = 60
//   E -> cached plan exceeds 60 works -> REPLAN -> re-derives IXSCAN{a}, the plan it
//        already had -> entry back to inactive, works ratcheted 6 -> 12
//   C -> works 6 <= 12 -> promoted ACTIVE again with works = 6, bar back to 60
//        "its like the higher work query never happened"  -- the reporter
//   E -> replan.  Forever.
//
// Instrumentation is the PROFILER, not explain(): explain() re-runs the multi-planner and
// would hide the cached-plan path entirely. Plus metrics.query.multiPlanner.classicMicros
// (optimizer CPU, server-side) and planCache.classic.replanned_plan_is_cached_plan (the
// wasteful-replan counter SERVER-98987 added in 8.2.0) from serverStatus.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('S2_DB', 'ch_s79039');
const COLL   = CH.env('S2_COLL', 'docs');
const NCHEAP = CH.envInt('S2_NCHEAP', 1000);
const EVAL   = CH.envInt('S2_EVAL', 900001);
const NC     = CH.envInt('S2_NC', 6);        // cheap queries per epoch
const NE     = CH.envInt('S2_NE', 6);        // expensive queries per epoch
const EPOCHS = CH.envInt('S2_EPOCHS', 4);
const ORDERS = CH.env('S2_ORDERS', 'alternating,blocked_CE,blocked_EC,shuffled').split(',');
const FW     = CH.env('S2_FRAMEWORK', 'trySbeRestricted');
const QUIET  = CH.envInt('S2_QUIET', 0) === 1;
const REP    = CH.envInt('S2_REP', 0);
const KIND   = CH.env('S2_KIND', 's79039_order');
const LABEL  = CH.env('S2_LABEL', COLL);

const d = db.getSiblingDB(DB);
const coll = d.getCollection(COLL);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });

// Measured once, before anything runs, so the sweep report can label each row without
// the count itself perturbing the serverStatus deltas taken around each order.
const N_E_ACTUAL = coll.countDocuments({ a: EVAL });

function runQuery(cls, k) {
  const q = cls === 'C' ? { a: (k % NCHEAP) + 1, b: 0 } : { a: EVAL, b: 0 };
  return coll.find(q).toArray();
}

// Pitfall 3 of docs/oracle-o3.md: the same-shape premise is VERIFIED, not assumed.
function keyOf(q) { const e = coll.find(q).explain(); return e.queryPlanner.planCacheKey; }
const premise = { C: keyOf({ a: 1, b: 0 }), E: keyOf({ a: EVAL, b: 0 }) };
premise.same_key = premise.C === premise.E;

function epochOrder(name) {
  const C = Array(NC).fill('C'), E = Array(NE).fill('E');
  switch (name) {
    case 'alternating': { const o = []; const n = Math.max(NC, NE);
                          for (let i = 0; i < n; i++) { if (i < NC) o.push('C'); if (i < NE) o.push('E'); }
                          return o; }
    case 'blocked_CE':  return C.concat(E);
    case 'blocked_EC':  return E.concat(C);
    case 'shuffled': {
      const o = C.concat(E);
      let s = 987654321;
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

function cacheState() {
  const e = coll.aggregate([{ $planCacheStats: {} }]).toArray();
  if (e.length === 0) return { present: false };
  const x = e[0];
  const works = x.works && x.works.low !== undefined ? x.works.low : x.works;
  const idx = JSON.stringify(x.cachedPlan || {}).match(/"indexName":"(\w+)"/);
  return { present: true, isActive: x.isActive, works: works, plan: idx ? idx[1] : '?' };
}

function counters() {
  const ss = db.serverStatus();
  const n = (v) => (v && v.low !== undefined ? v.low : v);
  const c = ss.metrics.query.planCache.classic;
  const qe = ss.metrics.queryExecutor;
  const mp = ss.metrics.query.multiPlanner;
  return { hits: n(c.hits), misses: n(c.misses), skipped: n(c.skipped),
           replanned: n(c.replanned),
           // SERVER-98987 (Fixed in 8.2.0): counts replans whose outcome is the plan that
           // was already cached -- i.e. provably wasted optimizer work. SERVER-79039's
           // "same plan" cycle increments this on every single expensive query.
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
      trace.push({ epoch: epoch, cls: cls, wall_ms: ns / 1e6,
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

  // --- the state variable itself: does the bar settle, or oscillate forever? -----------
  const worksSeries = trace.map((t) => (t.cache_after && t.cache_after.works) || null);
  let drops = 0, distinct = new Set();
  for (let i = 0; i < worksSeries.length; i++) {
    if (worksSeries[i] !== null) distinct.add(worksSeries[i]);
    if (i > 0 && worksSeries[i] !== null && worksSeries[i - 1] !== null
        && worksSeries[i] < worksSeries[i - 1]) drops++;
  }

  const sum = (rows, f) => rows.reduce((a, r) => a + (f(r) || 0), 0);
  const perEpoch = [];
  for (let e = 0; e < EPOCHS; e++) {
    const rows = trace.filter((t) => t.epoch === e);
    perEpoch.push({ epoch: e, docs: sum(rows, (r) => r.docsExamined),
                    millis: sum(rows, (r) => r.millis),
                    replans: rows.filter((r) => r.replanned).length,
                    multiplanned: rows.filter((r) => r.fromMultiPlanner).length,
                    from_cache: rows.filter((r) => r.fromPlanCache).length });
  }

  CH.emit({
    kind: KIND, coll: COLL, arm: LABEL, order: orderName, rep: REP, n_e: N_E_ACTUAL,
    nc: NC, ne: NE, epochs: EPOCHS, n_queries: trace.length, premise: premise,
    total_docs_examined: sum(trace, (r) => r.docsExamined),
    total_keys_examined: sum(trace, (r) => r.keysExamined),
    total_millis: sum(trace, (r) => r.millis),
    total_wall_ms: sum(trace, (r) => r.wall_ms),
    // Condition (c) of O3: a steady state, not a start-up transient. Compare LAST epochs.
    last_epoch: perEpoch[perEpoch.length - 1],
    per_epoch: perEpoch,
    n_replanned: trace.filter((r) => r.replanned).length,
    n_multiplanned: trace.filter((r) => r.fromMultiPlanner).length,
    works_distinct: Array.from(distinct).sort((a, b) => a - b),
    works_drops: drops,                      // how many times the bar was LOWERED again
    works_series: QUIET ? [] : worksSeries,
    by_class: ['C', 'E'].reduce((acc, k) => {
      const rows = trace.filter((r) => r.cls === k);
      if (rows.length) {
        acc[k] = { n: rows.length, docs: sum(rows, (r) => r.docsExamined),
                   keys: sum(rows, (r) => r.keysExamined),
                   millis: sum(rows, (r) => r.millis),
                   replans: rows.filter((r) => r.replanned).length,
                   multiplanned: rows.filter((r) => r.fromMultiPlanner).length,
                   plans: rows.reduce((a, r) => { const p = r.planSummary || '?'; a[p] = (a[p] || 0) + 1; return a; }, {}) };
      }
      return acc;
    }, {}),
    final_cache: cacheState(), counters: delta, trace: QUIET ? [] : trace,
  });
  print('order ' + orderName + ': ' + trace.length + ' queries, '
        + trace.filter((r) => r.replanned).length + ' replans, works seen ['
        + Array.from(distinct).sort((a, b) => a - b).join(',') + ']');
}

if (!QUIET) d.setProfilingLevel(0);

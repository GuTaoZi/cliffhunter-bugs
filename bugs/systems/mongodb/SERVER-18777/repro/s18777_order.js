// SERVER-18777: a rooted $or's branches take their cached plans with no trial, so a branch plan cached for one
// parameter class stays for the other, however bad, and is never replanned or evicted.
//
// One shape, find({$or: [{a: X, b: Y}, {c: K}]}). The first branch picks IXSCAN{a} or IXSCAN{b} and is cached per
// branch; the second has one plan (c_1). Classes: A = {a: i, b: 0} (good plan a_1), B = {a: 0, b: j} (good plan
// b_1); each under the other's plan scans 280,000 documents instead of 20. Arms:
//   orjoin  the default: branches subplanned, each branch's plan cached, no trial (the bug)
//   whole   internalQueryPlanOrChildrenIndependently=false: the whole $or planned and cached, with the trial
//   plain   the branch query alone, find({a: X, b: Y}): a cached plan with the trial
// Orders of NA A and NB B queries per epoch: alternating, blocked_AB, blocked_BA, shuffled, and the minimal pair
// pair_AAB / pair_BBB (the same final B query after two A queries or after two B queries).
// Traced runs read the profiler and $planCacheStats around each query; S3_QUIET=1 runs time queries only.
load((typeof process !== 'undefined' && process.env.CH_LIB) ||
     (typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB = CH.env('S3_DB', 'ch_s18777');
const COLL = CH.env('S3_COLL', 'orq');
const ARM = CH.env('S3_ARM', 'orjoin');
const ORDERS = CH.env('S3_ORDERS', 'alternating,blocked_AB,blocked_BA,shuffled,pair_AAB,pair_BBB').split(',');
const NA = CH.envInt('S3_NA', 6), NB = CH.envInt('S3_NB', 6), EPOCHS = CH.envInt('S3_EPOCHS', 3);
const NRARE = CH.envInt('S3_NRARE', 1000);
const K = CH.envInt('S3_K', 25);           // a filler document's c (its _id)
const FW = CH.env('S3_FRAMEWORK', 'trySbeRestricted');
const QUIET = CH.envInt('S3_QUIET', 0) === 1;
const REP = CH.envInt('S3_REP', 0);

const d = db.getSiblingDB(DB);
const coll = d.getCollection(COLL);
const admin = db.getSiblingDB('admin');
admin.runCommand({ setParameter: 1, internalQueryFrameworkControl: FW });
const prevOr = admin.runCommand({ getParameter: 1, internalQueryPlanOrChildrenIndependently: 1 })
                    .internalQueryPlanOrChildrenIndependently;
if (ARM === 'whole') admin.runCommand({ setParameter: 1, internalQueryPlanOrChildrenIndependently: false });

const n = (v) => (v && v.low !== undefined ? v.low : (v && v.toNumber ? v.toNumber() : v));
let nextA = 2, nextB = 2;
function query(cls) {
  const v = cls === 'A' ? nextA++ : nextB++;
  if (nextA > NRARE) nextA = 2;
  if (nextB > NRARE) nextB = 2;
  const branch = cls === 'A' ? { a: v, b: 0 } : { a: 0, b: v };
  return ARM === 'plain' ? branch : { $or: [branch, { c: K }] };
}

function order(name) {
  if (name === 'pair_AAB') return ['A', 'A', 'B'];
  if (name === 'pair_BBB') return ['B', 'B', 'B'];
  const A = Array(NA).fill('A'), B = Array(NB).fill('B');
  let one;
  switch (name) {
    case 'alternating': { one = []; for (let i = 0; i < Math.max(NA, NB); i++) { if (i < NA) one.push('A'); if (i < NB) one.push('B'); } break; }
    case 'blocked_AB': one = A.concat(B); break;
    case 'blocked_BA': one = B.concat(A); break;
    case 'shuffled': {
      one = A.concat(B);
      let s = 987654321;
      for (let i = one.length - 1; i > 0; i--) { s = (s * 1103515245 + 12345) & 0x7fffffff; const j = s % (i + 1); [one[i], one[j]] = [one[j], one[i]]; }
      break;
    }
    default: throw new Error('unknown order ' + name);
  }
  let all = [];
  for (let e = 0; e < EPOCHS; e++) all = all.concat(one);
  return all;
}

function cacheState() {
  return coll.aggregate([{ $planCacheStats: {} }]).toArray().map((x) => {
    const idx = JSON.stringify(x.cachedPlan || {}).match(/"indexName":"(\w+)"/);
    return { q: JSON.stringify(x.createdFromQuery && x.createdFromQuery.query), active: x.isActive,
             works: n(x.works), plan: idx ? idx[1] : '?' };
  });
}

function counters() {
  const ss = db.serverStatus();
  const c = ss.metrics.query.planCache.classic, mp = ss.metrics.query.multiPlanner, qe = ss.metrics.queryExecutor;
  return { hits: n(c.hits), misses: n(c.misses), replanned: n(c.replanned), evicted: n(c.cached_plans_evicted),
           mp_count: n(mp.classicCount), mp_micros: n(mp.classicMicros), mp_works: n(mp.classicWorks),
           scanned_keys: n(qe.scanned), scanned_docs: n(qe.scannedObjects) };
}

function resetProfiler() {
  d.setProfilingLevel(0);
  d.system.profile.drop();
  d.createCollection('system.profile', { capped: true, size: 64 * 1024 * 1024 });
  d.setProfilingLevel(2);
}

try {
  for (const name of ORDERS) {
    coll.getPlanCache().clear();
    if (!QUIET) resetProfiler();
    const c0 = counters();
    const trace = [];
    for (const cls of order(name)) {
      const q = query(cls);
      let got = 0;
      const ns = CH.timeNs(() => { got = coll.find(q).toArray().length; });
      trace.push({ cls: cls, wall_ms: ns / 1e6, nreturned_client: got, cache_after: QUIET ? null : cacheState() });
    }
    if (!QUIET) {
      d.setProfilingLevel(0);
      const prof = d.system.profile.find({ op: 'query', ns: DB + '.' + COLL }).sort({ ts: 1 }).toArray();
      for (let i = 0; i < trace.length && i < prof.length; i++) {
        const p = prof[i];
        Object.assign(trace[i], { docs: p.docsExamined, keys: p.keysExamined, millis: p.millis, plan: p.planSummary,
                                  fromPlanCache: p.fromPlanCache === true, fromMultiPlanner: p.fromMultiPlanner === true,
                                  replanned: p.replanned === true });
      }
    }
    const c1 = counters();
    const delta = {};
    for (const k of Object.keys(c1)) delta[k] = c1[k] - c0[k];
    const byClass = {};
    for (const k of ['A', 'B']) {
      const rows = trace.filter((t) => t.cls === k);
      if (!rows.length) continue;
      const w = rows.map((r) => r.wall_ms).sort((x, y) => x - y);
      byClass[k] = { n: rows.length, wall_ms_median: CH.quantile(w, 0.5), wall_ms_max: w[w.length - 1],
                     wall_ms_sum: w.reduce((x, y) => x + y, 0),
                     docs: QUIET ? null : rows.reduce((x, r) => x + (r.docs || 0), 0),
                     slow: QUIET ? null : rows.filter((r) => (r.docs || 0) > 100000).length,
                     plans: QUIET ? null : rows.reduce((acc, r) => { acc[r.plan] = (acc[r.plan] || 0) + 1; return acc; }, {}) };
    }
    const last = trace[trace.length - 1];
    CH.emit({ kind: 's18777_order', arm: ARM, order: name, rep: REP, quiet: QUIET, na: NA, nb: NB, epochs: EPOCHS,
              n_queries: trace.length, wall_ms_sum: trace.reduce((x, r) => x + r.wall_ms, 0), by_class: byClass,
              last_query: { cls: last.cls, wall_ms: last.wall_ms, docs: last.docs, plan: last.plan },
              counters: delta, final_cache: cacheState(), trace: QUIET ? [] : trace });
    print(ARM + ' ' + name + ': ' + trace.length + ' queries, ' + Object.entries(byClass).map(([k, v]) =>
          k + ' median ' + v.wall_ms_median.toFixed(1) + ' ms' + (v.slow === null ? '' : ', ' + v.slow + ' slow')).join('; ')
          + '; multiplans ' + delta.mp_count + ', replans ' + delta.replanned);
  }
} finally {
  if (!QUIET) d.setProfilingLevel(0);
  admin.runCommand({ setParameter: 1, internalQueryPlanOrChildrenIndependently: prevOr });
}

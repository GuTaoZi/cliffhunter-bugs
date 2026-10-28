// W5: run ONE FIXED MULTISET of queries in several ARRIVAL ORDERS (oracle O3).
//
// O3 asserts a metamorphic relation that needs no cost model at all:
//   a fixed multiset of queries should reach the same steady state, and cost about the
//   same in total, regardless of the order in which it arrives.
// Any difference is attributable to order-dependent state inside the server. The only
// such state here is the plan cache entry, whose 'works' bar is a monotone ratchet
// (plan_cache.h:723-748) that is never lowered except by a promotion.
//
// The state machine under test (plan_cache.h getNewEntryState + deactivate):
//   no entry                          -> create INACTIVE with works = W_new
//   INACTIVE, W_new >  bar            -> RATCHET: inactive, bar = max(bar+1, bar*2.0)
//   INACTIVE, W_new <= bar            -> PROMOTE to ACTIVE with works = W_new
//   ACTIVE,   W_new <= works          -> replace ACTIVE with works = W_new
//   ACTIVE,   W_new >  works          -> NO-OP (bar unchanged)
//   replan()                          -> deactivate: same works, isActive = false
// and in CachedPlanStage: replan if the cached plan exceeds
//   internalQueryCacheEvictionRatio (10.0) x decisionWorks works, UNLESS it first
//   produces 101 results or hits EOF (cached_plan.cpp:75-131).
//
// Instrumentation is the database profiler rather than explain(): explain() runs its own
// planning and would perturb the very state we are measuring. The profiler records
// docsExamined, planSummary, fromMultiPlanner, fromPlanCache and replanReason for the
// REAL queries, so the trace is of the thing itself.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W5_DB', 'w5');
const COLL   = CH.env('W5_COLL', 'docs');
const NRARE  = CH.envInt('W5_NRARE', 1000);
const NPER   = CH.envInt('W5_NPER', 10);     // E and H queries per class per epoch
const NMEDQ  = CH.envInt('W5_NMEDQ', 0);     // M queries per epoch (needs a W5_MEDIUM=1 build)
const MA     = CH.envInt('W5_MA', 9001);
const MB     = CH.envInt('W5_MB', 9002);
const EPOCHS = CH.envInt('W5_EPOCHS', 3);
const ORDERS = CH.env('W5_ORDERS', 'alternating,blocked_EH,blocked_HE,shuffled').split(',');
const FW     = CH.env('W5_FRAMEWORK', 'trySbeRestricted');
// W5_QUIET=1 drops the profiler and the per-query $planCacheStats polling. Those two cost
// real time and are what the resource harness must NOT pay for: with polling on, the
// client-side wall clock is dominated by two extra aggregations per query rather than by
// the queries. Quiet mode is therefore the only mode in which a CPU number means anything.
const QUIET  = CH.envInt('W5_QUIET', 0) === 1;

const d = db.getSiblingDB(DB);
const coll = d.getCollection(COLL);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });

// --- the multiset, and the orders it can arrive in ----------------------------------
// Every order below is a PERMUTATION of the same multiset: NPER 'E' and NPER 'H' per
// epoch. That is what makes any measured difference attributable to order alone.
function epochOrder(name) {
  const E = Array(NPER).fill('E'), H = Array(NPER).fill('H'), M = Array(NMEDQ).fill('M');
  const alt = () => { const o = []; for (let i = 0; i < NPER; i++) o.push('E', 'H'); return o; };
  switch (name) {
    case 'alternating': return alt();
    case 'blocked_EH':  return E.concat(H);
    case 'blocked_HE':  return H.concat(E);
    // The three below are permutations of the SAME multiset {M x NMEDQ, E x NPER, H x NPER};
    // only the position of the M queries differs. M is the instance that sets the replan bar.
    case 'M_first':     return M.concat(alt());
    case 'M_last':      return alt().concat(M);
    case 'M_middle':    { const a = alt(); return a.slice(0, a.length / 2).concat(M, a.slice(a.length / 2)); }
    case 'shuffled': {
      const o = E.concat(H).concat(M);
      let s = 987654321;                       // fixed seed: the permutation is reproducible
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

// --- observation helpers -------------------------------------------------------------
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
  const c = ss.metrics.query.planCache.classic;
  const n = (v) => (v && v.low !== undefined ? v.low : v);
  // queryExecutor.scanned/scannedObjects are SERVER-WIDE totals, so unlike the profiler's
  // per-operation docsExamined they also count work done by a cached-plan trial that was
  // then abandoned by a replan. The gap between the two is the hidden cost of replanning.
  const qe = ss.metrics.queryExecutor;
  return { hits: n(c.hits), misses: n(c.misses), skipped: n(c.skipped),
           replanned: n(c.replanned), evicted: n(c.cached_plans_evicted),
           inactive_replaced: n(c.inactive_cached_plans_replaced),
           executor_scanned_keys: n(qe.scanned), executor_scanned_docs: n(qe.scannedObjects) };
}

function resetProfiler() {
  if (QUIET) return;
  d.setProfilingLevel(0);
  d.system.profile.drop();
  // 64 MB: the default 1 MB capped collection can roll over mid-run and silently drop
  // the early transitions, which are the ones that matter.
  d.createCollection('system.profile', { capped: true, size: 64 * 1024 * 1024 });
  d.setProfilingLevel(2);
}

// --- the run -------------------------------------------------------------------------
let valueCursor = 0;   // never reuse a rare value, so no query repeats within a run
for (const orderName of ORDERS) {
  coll.getPlanCache().clear();
  resetProfiler();
  const c0 = counters();
  const trace = [];

  for (let epoch = 0; epoch < EPOCHS; epoch++) {
    for (const cls of epochOrder(orderName)) {
      const v = (valueCursor++ % NRARE) + 1;
      const q = cls === 'E' ? { a: v, b: 0 }
              : cls === 'H' ? { a: 0, b: v }
              : { a: MA, b: MB };
      const before = QUIET ? null : cacheState();
      const ns = CH.timeNs(() => coll.find(q).toArray());
      const after = QUIET ? null : cacheState();
      trace.push({ epoch: epoch, cls: cls, value: v, wall_ms: ns / 1e6,
                   cache_before: before, cache_after: after });
    }
  }

  if (!QUIET) d.setProfilingLevel(0);
  // Join the profiler's per-operation facts onto the trace, in execution order.
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
    kind: 'w5_order', coll: COLL, order: orderName, nper: NPER, nmedq: NMEDQ, epochs: EPOCHS,
    n_queries: trace.length,
    // The O3 comparison: identical multiset, so these SHOULD match across orders.
    total_docs_examined: sum(trace, (r) => r.docsExamined),
    total_millis: sum(trace, (r) => r.millis),
    // Wall-clock measured client-side, as a cross-check on the profiler's millis.
    total_wall_ms: sum(trace, (r) => r.wall_ms),
    // Steady state: the final epoch, after any warm-up transient has settled.
    last_epoch_docs_examined: sum(lastEpoch, (r) => r.docsExamined),
    last_epoch_millis: sum(lastEpoch, (r) => r.millis),
    n_catastrophic: trace.filter((r) => (r.docsExamined || 0) > 1000).length,
    by_class: ['E', 'H', 'M'].reduce((acc, k) => {
      const rows = trace.filter((r) => r.cls === k);
      if (rows.length) {
        acc[k] = { n: rows.length, docs: sum(rows, (r) => r.docsExamined),
                   millis: sum(rows, (r) => r.millis),
                   max_docs: Math.max.apply(null, rows.map((r) => r.docsExamined || 0)) };
      }
      return acc;
    }, {}),
    final_cache: cacheState(), counters: delta, trace: QUIET ? [] : trace,
  });
  print('order ' + orderName + ': done (' + trace.length + ' queries, '
        + trace.filter((r) => (r.docsExamined || 0) > 1000).length + ' catastrophic)');
}

if (!QUIET) d.setProfilingLevel(0);
print(QUIET ? 'quiet mode: no profiler, no per-query polling' : 'profiling disabled');

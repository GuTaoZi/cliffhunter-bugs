// W5 addendum: is this a METASTABLE FAILURE in the sense of Huang et al., OSDI'22?
//
// "Metastable Failures in the Wild" (OSDI'22) defines the class precisely:
//     "The distinguishing characteristic of a metastable failure is that the sustaining
//      effect keeps the system in the metastable failure state even after the trigger is
//      removed."
// with a two-part causal decomposition -- a TRIGGER (transient) and a SUSTAINING EFFECT
// (a feedback loop that persists once established). Their taxonomy separates workload
// amplification from CAPACITY DEGRADATION amplification, and §6.1 explicitly licenses a
// sustaining effect with no amplification at all.
//
// W5 appears to be exactly that, in a query planner:
//     trigger           two executions of a legitimately expensive query (class M)
//     sustaining effect the plan cache's replan bar, latched at 10 x 200,001 works --
//                       larger than the collection, so nothing can ever trip it
//     amplification     none; this is pure capacity degradation
//
// The claim that makes it metastable rather than merely slow is that removing the trigger
// does not help. This script tests that directly: run the trigger twice, then run ONLY the
// other query classes and watch whether the bar ever comes back down.
//
// Why it cannot recover, from the state machine (plan_cache.h getNewEntryState):
//   active, W_new <= bar -> bar := W_new    (the only path that LOWERS the bar)
//   active, W_new >  bar -> no-op
// The cheap classes never reach that path, because they never replan: under the cached
// plan, class E is fast (no replan triggered) and class H is catastrophic but still far
// under the 2,000,010 bar (no replan triggered). With no replan there is no new works
// measurement, so nothing ever writes a lower value. The bar is absorbing.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W5_DB', 'w5');
const COLL   = CH.env('W5_COLL', 'docs_bar');
const NRARE  = CH.envInt('W5_NRARE', 900);
const ROUNDS = CH.envInt('W5_MS_ROUNDS', 8);
const PER    = CH.envInt('W5_MS_PER', 50);     // E/H queries per round, after the trigger
const MA     = CH.envInt('W5_MA', 9001);
const MB     = CH.envInt('W5_MB', 9002);

const d = db.getSiblingDB(DB);
const c = d.getCollection(COLL);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });
db.adminCommand({ setParameter: 1, planRankerMode: 'multiPlanning' });

function state() {
  const e = c.aggregate([{ $planCacheStats: {} }]).toArray();
  if (!e.length) return { present: false };
  const x = e[0];
  const w = x.works && x.works.low !== undefined ? x.works.low : x.works;
  const m = JSON.stringify(x.cachedPlan || {}).match(/"indexName":"(\w+)"/);
  return { present: true, isActive: x.isActive, works: w, plan: m ? m[1] : '?' };
}

c.getPlanCache().clear();
const cleared = state();

// --- the trigger, and it is deliberately brief -------------------------------------
for (let i = 0; i < 2; i++) c.find({ a: MA, b: MB }).toArray();
const afterTrigger = state();

// --- the trigger is now gone. Run only the other classes. --------------------------
const trace = [];
let v = 0;
for (let r = 1; r <= ROUNDS; r++) {
  for (let i = 0; i < PER; i++) {
    const k = (v++ % NRARE) + 1;
    c.find({ a: k, b: 0 }).toArray();      // class E
    c.find({ a: 0, b: k }).toArray();      // class H -- the one paying 780,000 docs
  }
  trace.push({ queries_since_trigger: r * PER * 2, state: state() });
}

// --- and a long run of the CHEAP class alone, in case E can reset it ---------------
for (let i = 0; i < 500; i++) c.find({ a: (i % NRARE) + 1, b: 0 }).toArray();
const afterCheapOnly = state();

const recovered = afterCheapOnly.works !== afterTrigger.works;
CH.emit({
  kind: 'w5_metastable', coll: COLL,
  cleared: cleared, after_trigger: afterTrigger, trace: trace,
  after_cheap_only: afterCheapOnly,
  total_queries_after_trigger: ROUNDS * PER * 2 + 500,
  recovered: recovered,
  verdict: recovered ? 'recovers -- NOT metastable'
                     : 'never recovers -- the sustaining effect is absorbing',
});
print('trigger: M x2 -> ' + JSON.stringify(afterTrigger));
print('after ' + (ROUNDS * PER * 2 + 500) + ' queries with NO trigger -> '
      + JSON.stringify(afterCheapOnly));
print(recovered ? 'RECOVERED' : 'NEVER RECOVERED (metastable)');
c.getPlanCache().clear();

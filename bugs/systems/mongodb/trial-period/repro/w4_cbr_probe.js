// Does MongoDB's cost-based ranker rescue W4's regime?
//
// This matters for scoping the whole finding. The multi-plan trial period is the default
// plan-selection mechanism through 8.2; per MongoDB's docs, 8.3 makes "multi-planning with
// a CBR backup" the default for eligible queries. If CBR picks correctly here, then W4
// characterises a defect in the LEGACY default rather than an open problem -- and the
// honest contribution is the closed-form rule for which workloads it mis-plans.
//
// On 8.2.12 the valid planRankerMode values are 'multiPlanning' and 'automaticCE'
// ('mixed'/'costBased' from the master IDL are rejected with BadValue).
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB    = CH.env('W4_DB', 'w4');
const COLLS = CH.env('W4_COLLS', 'docs,docs_k1000,docs_mirror').split(',');
const MODES = CH.env('W4_RANKERS', 'multiPlanning,automaticCE').split(',');
const REPS  = CH.envInt('W4_REPS', 5);

const d = db.getSiblingDB(DB);
const QUERY = { a: 1, b: 5 };
db.adminCommand({ setParameter: 1, internalQueryPlanEvaluationMaxResults: 101 });

function planId(node) {
  const names = [];
  (function walk(n) {
    if (!n || typeof n !== 'object') return;
    if (n.stage === 'IXSCAN' && n.indexName) names.push('ixscan:' + n.indexName);
    if (n.stage === 'COLLSCAN') names.push('collscan');
    for (const k of ['inputStage', 'innerStage', 'outerStage']) if (n[k]) walk(n[k]);
    if (Array.isArray(n.inputStages)) n.inputStages.forEach(walk);
  })(node);
  return names.length ? names.sort().join('+') : 'unknown';
}

const original = db.adminCommand({ getParameter: 1, planRankerMode: 1 }).planRankerMode;
for (const mode of MODES) {
  try { db.adminCommand({ setParameter: 1, planRankerMode: mode }); }
  catch (e) {
    CH.emit({ kind: 'w4_cbr', ranker: mode, error: e.codeName || String(e) });
    continue;
  }
  for (const collName of COLLS) {
    const coll = d.getCollection(collName);
    coll.getPlanCache().clear();
    const ex = coll.find(QUERY).explain('executionStats');
    // Clear the cache every rep: the plan choice is what we are pricing, not cache hits.
    const samples = [];
    for (let i = 0; i < REPS; i++) {
      coll.getPlanCache().clear();
      samples.push(CH.timeNs(() => coll.find(QUERY).toArray()));
    }
    CH.emit(Object.assign(
      { kind: 'w4_cbr', ranker: mode, coll: collName,
        winner: planId((ex.queryPlanner || {}).winningPlan) },
      CH.planFacts(ex), { latency: CH.stats(samples) }));
  }
}
db.adminCommand({ setParameter: 1, planRankerMode: original });
print('restored planRankerMode = ' + original);

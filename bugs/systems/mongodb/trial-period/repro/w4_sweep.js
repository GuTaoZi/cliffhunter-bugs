// W4 sweep: vary internalQueryPlanEvaluationMaxResults and ask whether the plan the
// ranker picks flips. Oracle O2 (evidence sufficiency): a decision must not be taken on
// a prefix that could not distinguish the candidates.
//
// What the source says should happen (predicted BEFORE the run, and confirmed to the digit):
//
//   score = 1 + advanced/works + epsilon*(noFetch + noSort + noIxisect) + 1 if isEOF
//   epsilon = 1e-4.  Productivity: plan_ranker.h:53-107 (calculateScore).
//   EOF bonus of +1: plan_ranker_util.h:201-247, applied in pickBestPlan AFTER
//   calculateScore -- NOT inside it, which is why it is easy to miss when reading.
//
//   * workAllPlans() (multi_plan.cpp:504-596) works every candidate round-robin ONE work
//     per round, and ends the trial for EVERYONE as soon as ANY candidate either reaches
//     maxResults results or hits EOF. So 'works' is essentially EQUAL across candidates,
//     and productivity therefore ranks plans by "results in the first W works" -- a
//     PREFIX RACE, not a comparison of total cost.
//   * The EOF bonus is the only term in the formula that carries information about a
//     plan's TOTAL cost: it says "this plan finished, so its whole scan was cheap".
//
// The two stopping conditions therefore RACE, and which one fires decides everything:
//
//   maxResults <= (number of matching documents)
//       {a:1} fills the batch first, in exactly maxResults works: productivity 1.0 vs 0.0.
//       {a:1} wins 2.0002 to 1.0002 and runs a ~59x more expensive scan. The EOF bonus
//       never fires, because the batch-full condition stopped the trial before {b:1}
//       could reach the end of its (much shorter) index range.
//   maxResults > (number of matching documents)
//       Nobody can fill the batch, so the trial instead runs until {b:1} exhausts b=5.
//       {b:1} hits EOF, collects the +1, and wins ~2.0022 to ~1.0022 -- correctly, and
//       for a principled reason.
//
// So the defect is located in the STOPPING RULE, not in the score: the full-batch
// condition pre-empts the EOF condition, and the EOF bonus is the only term that would
// have identified the cheaper plan. W4_NMATCH is set equal to the knob to make the bad
// condition win; building one dataset per knob value is how condition (c) is tested.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB      = CH.env('W4_DB', 'w4');
const COLL    = CH.env('W4_COLL', 'docs');
const REPS    = CH.envInt('W4_REPS', 10);
const WARMUP  = CH.envInt('W4_WARMUP', 2);
const MAXRES  = CH.env('W4_MAXRES', '101,1000,100000').split(',').map((s) => parseInt(s.trim(), 10));
const FW      = CH.env('W4_FRAMEWORK', 'trySbeRestricted');

const d = db.getSiblingDB(DB);
const coll = d.getCollection(COLL);
const QUERY = { a: 1, b: 5 };

db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });
print('internalQueryFrameworkControl = ' + FW + '  collection = ' + DB + '.' + COLL);

// --- plan identification -------------------------------------------------------------
// Name a candidate by the access path it uses, so trial rows can be matched to plans.
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

// One row per candidate plan's TRIAL run: the evidence the ranker actually saw.
function trialRows(ex) {
  const all = (ex.executionStats || {}).allPlansExecution || [];
  return all.map((p) => {
    const root = p.executionStages || {};
    const works = root.works === undefined ? null : root.works;
    const adv = root.advanced === undefined ? null : root.advanced;
    return {
      plan: planId(root),
      works: works,
      advanced: adv,
      // The scorer's own productivity term, recomputed from the counters it reads.
      productivity: works ? adv / works : null,
      // score = 1 + productivity + epsilons; epsilons are <= 3e-4 and cannot close a gap.
      score_est: works ? 1 + adv / works : null,
      // The server's OWN score, exposed per candidate in allPlansExecution. Recorded so
      // the claim rests on the ranker's arithmetic rather than on our reimplementation
      // of it -- the two agreed to four decimals on first contact.
      score: p.score === undefined ? null : p.score,
      trial_keys: p.totalKeysExamined === undefined ? null : p.totalKeysExamined,
      trial_docs: p.totalDocsExamined === undefined ? null : p.totalDocsExamined,
      is_eof: root.isEOF === undefined ? null : root.isEOF,
    };
  });
}

function planCacheEntries() {
  try {
    return coll.aggregate([{ $planCacheStats: {} }]).toArray().map((e) => ({
      plan: planId((e.cachedPlan || {})),
      isActive: e.isActive,
      works: e.works && e.works.low !== undefined ? e.works.low : e.works,
      // SERVER-13675's policy artifact: ties are supposed not to be cached.
      // 'tieForBest'/'scores' surface here when the server exposes them.
      scores: e.scores || null,
    }));
  } catch (e) { return [{ error: e.codeName || String(e) }]; }
}

function run(hint) {
  let c = coll.find(QUERY);
  if (hint) c = c.hint(hint);
  return c.toArray();
}
function latency(hint) {
  for (let i = 0; i < WARMUP; i++) run(hint);
  const s = [];
  for (let i = 0; i < REPS; i++) s.push(CH.timeNs(() => run(hint)));
  return CH.stats(s);
}

// --- ground truth --------------------------------------------------------------------
// What each plan ACTUALLY costs run to completion. This is the yardstick the trial
// period is meant to approximate, and condition (b)'s counterfactual measurement.
print('--- ground truth: forced plans ---');
for (const h of [{ a: 1 }, { b: 1 }]) {
  coll.getPlanCache().clear();
  const ex = coll.find(QUERY).hint(h).explain('executionStats');
  CH.emit(Object.assign(
    { kind: 'w4_truth', coll: COLL, hint: JSON.stringify(h), plan: planId((ex.executionStats || {}).executionStages) },
    CH.planFacts(ex), { latency: latency(h) }));
}

// --- the sweep -----------------------------------------------------------------------
print('--- sweep internalQueryPlanEvaluationMaxResults ---');
for (const mr of MAXRES) {
  db.adminCommand({ setParameter: 1, internalQueryPlanEvaluationMaxResults: mr });
  coll.getPlanCache().clear();

  // allPlansExecution gives the per-candidate TRIAL counters plus the winner's full run.
  const ex = coll.find(QUERY).explain('allPlansExecution');
  const facts = CH.planFacts(ex);
  const winner = planId((ex.queryPlanner || {}).winningPlan);
  const rejected = ((ex.queryPlanner || {}).rejectedPlans || []).map(planId);

  // Run the query for real so the decision gets persisted, then read what was frozen.
  coll.getPlanCache().clear();
  const lat = latency(null);
  const cache = planCacheEntries();

  CH.emit(Object.assign({
    kind: 'w4_point', coll: COLL, max_results: mr, framework: FW,
    winner: winner, rejected: rejected,
    trial: trialRows(ex),
    plan_cache: cache,
  }, facts, { latency: lat }));
}

db.adminCommand({ setParameter: 1, internalQueryPlanEvaluationMaxResults: 101 });
print('restored internalQueryPlanEvaluationMaxResults = 101');

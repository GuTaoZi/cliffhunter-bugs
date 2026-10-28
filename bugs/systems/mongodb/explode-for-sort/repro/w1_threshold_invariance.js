// Is the cliff an artifact of WHERE the constant sits, or of the heuristic's STRUCTURE?
//
// The objection this answers: "any threshold produces a discontinuity -- move it to 1000
// and you'd see a gap at 1000->1001 too, so finding a gap proves nothing."
//
// That is true and it is the right question. The test that separates the two cases:
// move the constant and measure whether the cliff MAGNITUDE changes.
//   - if the cliff shrinks as the constant rises, the constant was merely too low -> tuning bug
//   - if the cliff is invariant, no value of the constant fixes it -> structural bug
//
// Prediction for explode-for-sort: merge cost ~ (K + limit), fallback cost ~ K * docsPerTag,
// so ratio ~ docsPerTag, INDEPENDENT of K. If that holds, retuning cannot help.
//
// Also measures the CROSSOVER: cost of the abandoned plan vs the adopted plan at the SAME
// workload point. A well-placed threshold sits where the two curves cross (ratio ~ 1).
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W1_DB', 'w1');
const REPS   = CH.envInt('TI_REPS', 5);
const WARMUP = CH.envInt('TI_WARMUP', 2);
const LIMIT  = CH.envInt('W1_LIMIT', 20);
const KNOBS  = CH.env('TI_KNOBS', '200,1000').split(',').map((s) => parseInt(s.trim(), 10));

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });

function inList(k) { const a = []; for (let i = 0; i < k; i++) a.push(i); return a; }
function run(k) { return d.docs.find({ tag: { $in: inList(k) } }).sort({ ts: 1 }).limit(LIMIT).toArray(); }

function measure(k, knobValue, label) {
  db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: knobValue });
  d.docs.getPlanCache().clear();
  const ex = d.docs.find({ tag: { $in: inList(k) } }).sort({ ts: 1 }).limit(LIMIT).explain('executionStats');
  const facts = CH.planFacts(ex);
  for (let i = 0; i < WARMUP; i++) run(k);
  const s = []; for (let i = 0; i < REPS; i++) s.push(CH.timeNs(() => run(k)));
  CH.emit(Object.assign({ kind: 'ti_point', k: k, knob_value: knobValue, role: label },
                        facts, { latency: CH.stats(s) }));
  return facts;
}

const ntags = d.docs.distinct('tag').length;
CH.emit({ kind: 'ti_setup', docs: d.docs.countDocuments({}), ntags: ntags });

for (const K of KNOBS) {
  if (ntags < K + 2) { print('skip knob ' + K + ': only ' + ntags + ' distinct tags'); continue; }
  measure(K,     K, 'at_threshold');       // last k that still gets the merge plan
  measure(K + 1, K, 'past_threshold');     // first k that falls back
  // The counterfactual: the SAME past-threshold workload with the constant raised, i.e.
  // the cost of the plan the heuristic threw away. This is the crossover measurement.
  measure(K + 1, K * 10, 'abandoned_plan_forced');
}
db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: 200 });

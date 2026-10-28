// The remaining candidate justification for the explode cap: FAN-OUT.
//
// merge examines ~ (K + limit) entries; the sort examines ~ (K x docsPerTag).
// So when docsPerTag is ~1 the sort examines about as many entries as the merge does --
// and the merge additionally pays for K live index cursors. That is the regime where
// "too many ixscans spoil the performance" should actually be true.
//
// Builds a collection with UNIQUE tags (docsPerTag = 1) and sweeps K upward to find the
// point where exploding genuinely becomes the worse plan.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB    = CH.env('FX_DB', 'w1u');
const N     = CH.envInt('FX_N', 2000000);
const LIMIT = CH.envInt('FX_LIMIT', 20);
const REPS  = CH.envInt('FX_REPS', 3);
const KS    = CH.env('FX_KS', '201,1000,5000,20000,50000,100000')
                .split(',').map((s) => parseInt(s.trim(), 10));

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });

let seed = 999;
function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed; }

if (d.docs.countDocuments({}) !== N) {
  d.docs.drop();
  print('building ' + N + ' docs with UNIQUE tag (docsPerTag = 1)');
  let ins = 0;
  while (ins < N) {
    const b = []; const upto = Math.min(20000, N - ins);
    for (let j = 0; j < upto; j++) { const i = ins + j; b.push({ _id: i, tag: i, ts: rnd() }); }
    d.docs.insertMany(b, { ordered: false }); ins += upto;
  }
  d.docs.createIndex({ tag: 1, ts: 1 });
}

function measure(k, knob) {
  db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: knob });
  d.docs.getPlanCache().clear();
  const inList = []; for (let i = 0; i < k; i++) inList.push(i);
  let keys = null, stage = null, best = Infinity;
  for (let i = 0; i < REPS; i++) {
    const ex = d.docs.find({ tag: { $in: inList } }).sort({ ts: 1 }).limit(LIMIT)
                .explain('executionStats');
    const f = CH.planFacts(ex);
    keys = f.totalKeysExamined; stage = f.stage_summary.split('>IXSCAN')[0];
    if (f.executionTimeMillis < best) best = f.executionTimeMillis;
  }
  return { keys: keys, stage: stage, ms: best };
}

for (const k of KS) {
  const sortPlan  = measure(k, 1);          // cap of 1 => never explode => blocking SORT
  const mergePlan = measure(k, 200000);     // cap huge  => always explode => SORT_MERGE
  CH.emit({ kind: 'fx_point', k: k, docs_per_tag: 1,
            sort_stage: sortPlan.stage, sort_keys: sortPlan.keys, sort_ms: sortPlan.ms,
            merge_stage: mergePlan.stage, merge_keys: mergePlan.keys, merge_ms: mergePlan.ms });
}
db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: 200 });

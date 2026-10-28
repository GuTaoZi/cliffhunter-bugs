// Where, if anywhere, does the blocking SORT actually BEAT the exploded SORT_MERGE?
//
// Theory: merge examines ~ (limit + K) index entries because it is lazy; the sort examines
// ALL matching entries regardless of limit. So the merge should win until the limit
// approaches the full result set -- and even there, merging K pre-sorted runs (N log K)
// should beat sorting from scratch (N log N).
//
// `limit` is exactly the variable explodeForSort() never reads.
//
// Measured with explain('executionStats'): it runs the plan server-side without shipping
// a million documents to the shell, and reports server-side time and work counters.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W1_DB', 'w1');
const K      = CH.envInt('LX_K', 201);
const REPS   = CH.envInt('LX_REPS', 3);
const LIMITS = CH.env('LX_LIMITS', '20,100,1000,10000,100000,500000,1675134')
                 .split(',').map((s) => parseInt(s.trim(), 10));

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });
const inList = []; for (let i = 0; i < K; i++) inList.push(i);

function measure(limit, knob) {
  db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: knob });
  d.docs.getPlanCache().clear();
  let keys = null, stage = null, best = Infinity;
  for (let i = 0; i < REPS; i++) {
    const ex = d.docs.find({ tag: { $in: inList } }).sort({ ts: 1 }).limit(limit)
                .explain('executionStats');
    const f = CH.planFacts(ex);
    keys = f.totalKeysExamined; stage = f.stage_summary.split('>IXSCAN')[0];
    if (f.executionTimeMillis < best) best = f.executionTimeMillis;   // best-of, server-side
  }
  return { keys: keys, stage: stage, ms: best };
}

for (const limit of LIMITS) {
  const sortPlan  = measure(limit, 200);        // default: falls back to blocking SORT at k=201
  const mergePlan = measure(limit, 400);        // cap raised: explodes into SORT_MERGE
  CH.emit({ kind: 'lx_point', k: K, limit: limit,
            sort_stage: sortPlan.stage,  sort_keys: sortPlan.keys,  sort_ms: sortPlan.ms,
            merge_stage: mergePlan.stage, merge_keys: mergePlan.keys, merge_ms: mergePlan.ms });
}
db.adminCommand({ setParameter: 1, internalQueryMaxScansToExplode: 200 });

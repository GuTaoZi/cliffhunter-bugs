// Noise floor: repeat ONE unchanged workload many times and characterise this host's
// per-metric variation. Per the experiment design, no cliff magnitude may be reported
// unless it exceeds 3x this floor. Run before trusting any measurement on a new host.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('NF_DB', 'w1');
const REPS   = CH.envInt('NF_REPS', 30);
const WARMUP = CH.envInt('NF_WARMUP', 5);
const K      = CH.envInt('NF_K', 100);
const LIMIT  = CH.envInt('NF_LIMIT', 20);

const d = db.getSiblingDB(DB);
function inList(k) { const a = []; for (let i = 0; i < k; i++) a.push(i); return a; }
function runQuery() {
  return d.docs.find({ tag: { $in: inList(K) } }).sort({ ts: 1 }).limit(LIMIT).toArray();
}

for (let i = 0; i < WARMUP; i++) runQuery();
const samples = [], keys = [];
for (let i = 0; i < REPS; i++) {
  samples.push(CH.timeNs(runQuery));
  if (i % 10 === 0) {
    const ex = d.docs.find({ tag: { $in: inList(K) } }).sort({ ts: 1 }).limit(LIMIT)
                .explain('executionStats');
    keys.push(CH.planFacts(ex).totalKeysExamined);
  }
}
const st = CH.stats(samples);
CH.emit({
  kind: 'noise_floor', db: DB, k: K, reps: REPS,
  latency: st,
  // Spread as a fraction of the median -- this is "the floor".
  floor_rel_p90_p10: (st.p90_ms - st.p10_ms) / st.median_ms,
  min_reportable_ratio: 1 + 3 * ((st.p90_ms - st.p10_ms) / st.median_ms),
  keys_examined_samples: keys,
  keys_deterministic: keys.every((v) => v === keys[0]),
});

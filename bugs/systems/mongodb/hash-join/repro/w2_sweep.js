// W2 sweep: grow the foreign collection one document across 10000 and watch the
// join algorithm flip from hash join to nested loop. Oracle O1.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W2_DB', 'w2');
const REPS   = CH.envInt('W2_REPS', 5);
const WARMUP = CH.envInt('W2_WARMUP', 1);
const SIZES  = CH.env('W2_SIZES', '9998,9999,10000,10001,10002,10010')
                 .split(',').map((s) => parseInt(s.trim(), 10));
const FW     = CH.env('W2_FRAMEWORK', 'trySbeEngine');

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });
print('internalQueryFrameworkControl = ' + FW);

function pipeline(foreign) {
  return [
    { $lookup: { from: foreign, localField: 'f', foreignField: 'g', as: 'out' } },
    { $group: { _id: null, total: { $sum: { $size: '$out' } } } },
  ];
}

for (const size of SIZES) {
  const foreign = 'foreign_' + size;
  const ex = d.local.explain('executionStats').aggregate(pipeline(foreign));
  const facts = CH.planFacts(ex);
  const join = CH.joinAlgo(ex);

  for (let i = 0; i < WARMUP; i++) d.local.aggregate(pipeline(foreign)).toArray();
  const samples = [];
  for (let i = 0; i < REPS; i++) samples.push(CH.timeNs(() => d.local.aggregate(pipeline(foreign)).toArray()));

  CH.emit(Object.assign(
    { kind: 'w2_point', foreign_docs: size, join_algo: join, framework: FW },
    facts, { latency: CH.stats(samples) }));
}

// Restore the server default so a later run of another workload is not silently
// executed under a different engine (this bit us once already).
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: "trySbeRestricted" });
print("restored internalQueryFrameworkControl = trySbeRestricted");

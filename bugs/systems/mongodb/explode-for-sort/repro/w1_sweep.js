// W1 sweep: vary |$in| across the 200 threshold, holding the query shape and data fixed.
// Oracle O1 (workload continuity): a one-unit change in k must not step the cost.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W1_DB', 'w1');
const REPS   = CH.envInt('W1_REPS', 20);
const WARMUP = CH.envInt('W1_WARMUP', 3);
const LIMIT  = CH.envInt('W1_LIMIT', 20);
const KS     = CH.env('W1_KS', '50,100,150,190,195,199,200,201,205,210,250,300')
                 .split(',').map((s) => parseInt(s.trim(), 10));

const FW = CH.env('W1_FRAMEWORK', 'trySbeRestricted');  // pin: W2 leaves the server on trySbeEngine

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: FW });
print('internalQueryFrameworkControl = ' + FW);

function inList(k) { const a = []; for (let i = 0; i < k; i++) a.push(i); return a; }
function runQuery(k) {
  return d.docs.find({ tag: { $in: inList(k) } }).sort({ ts: 1 }).limit(LIMIT).toArray();
}

for (const k of KS) {
  d.docs.getPlanCache().clear();

  const ex = d.docs.find({ tag: { $in: inList(k) } }).sort({ ts: 1 }).limit(LIMIT)
              .explain('executionStats');
  const facts = CH.planFacts(ex);

  for (let i = 0; i < WARMUP; i++) runQuery(k);
  const samples = [];
  for (let i = 0; i < REPS; i++) samples.push(CH.timeNs(() => runQuery(k)));

  CH.emit(Object.assign({ kind: 'w1_point', k: k, limit: LIMIT, framework: FW },
                        facts, { latency: CH.stats(samples) }));
}

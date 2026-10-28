// W4 dataset: the 101-document trial period (oracle O2, Pattern B).
//
// Two single-field indexes, a two-predicate equality query, and a record layout chosen so
// that the PREFIX each plan sees during the trial period inverts their true total cost.
//
// Default ("normal") layout, in recordId space:
//   [0, P)        {a:2, b:5}  -- matches b, not a  => poison for the {b:1} prefix
//   [P, P+M)      {a:1, b:5}  -- the only M real matches
//   [P+M, N)      {a:1, b:7}  -- matches a, not b  => the bulk of the {a:1} scan
//
// Index {a:1} is ordered (a, recordId), so scanning a=1 begins at recordId P and its
// first M documents are ALL matches: productivity M/M = 1.0.
// Index {b:1} scanning b=5 begins at recordId 0 and its first P documents are all
// non-matches: productivity 0/M = 0.0.
// Truth is the other way round: {b:1} examines P+M documents in total, {a:1} examines
// N-P. The trial period sees exactly the prefix that ranks them backwards.
//
// W4_MATCH is the knob this attacks: set it equal to whatever
// internalQueryPlanEvaluationMaxResults is and the trial fills its batch on the bad plan.
// Building one dataset per knob value is how condition (c) (invariance) is tested.
//
// W4_MIRROR=1 swaps which index gets the good prefix, holding everything else fixed:
//   [0, P)        {a:1, b:2}  -- poison for the {a:1} prefix
//   [P, P+M)      {a:1, b:5}  -- the matches
//   [P+M, N)      {a:3, b:5}  -- the bulk of the {b:1} scan
// Now {b:1} has the perfect prefix and is the expensive plan. This exists to test whether
// a tie is resolved by anything meaningful or merely by candidate ordering.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W4_DB', 'w4');
const COLL   = CH.env('W4_COLL', 'docs');
const N      = CH.envInt('W4_N', 3000000);
const P      = CH.envInt('W4_NPOISON', 50000);   // decoys ahead of the matches
const M      = CH.envInt('W4_NMATCH', 101);      // == internalQueryPlanEvaluationMaxResults
const MIRROR = CH.envInt('W4_MIRROR', 0) === 1;
const BATCH  = CH.envInt('W4_BATCH', 20000);
const PADLEN = CH.envInt('W4_PADLEN', 64);

const d = db.getSiblingDB(DB);
const c = d.getCollection(COLL);
c.drop();

const pad = 'x'.repeat(PADLEN);
const M0 = P;      // [0, M0)  poison
const M1 = P + M;  // [M0, M1) the answer;  [M1, N) tail

function docAt(i) {
  if (MIRROR) {
    if (i < M0) return { _id: i, a: 1, b: 2, pad: pad };
    if (i < M1) return { _id: i, a: 1, b: 5, pad: pad };
    return { _id: i, a: 3, b: 5, pad: pad };
  }
  if (i < M0) return { _id: i, a: 2, b: 5, pad: pad };
  if (i < M1) return { _id: i, a: 1, b: 5, pad: pad };
  return { _id: i, a: 1, b: 7, pad: pad };
}

// Which index ends up with the perfect prefix, and what each plan costs to completion.
const goodPrefix = MIRROR ? 'ixscan:b_1' : 'ixscan:a_1';
const cost = MIRROR ? { 'ixscan:a_1': M1, 'ixscan:b_1': N - M0 }
                    : { 'ixscan:a_1': N - M0, 'ixscan:b_1': M1 };

print('building ' + N + ' docs into ' + DB + '.' + COLL + (MIRROR ? ' (MIRROR)' : '')
      + ' poison=[0,' + M0 + ') match=[' + M0 + ',' + M1 + ') tail=[' + M1 + ',' + N + ')');
let inserted = 0;
while (inserted < N) {
  const batch = [];
  const upto = Math.min(BATCH, N - inserted);
  for (let j = 0; j < upto; j++) batch.push(docAt(inserted + j));
  c.insertMany(batch, { ordered: false });
  inserted += upto;
  if (inserted % (BATCH * 25) === 0) print('  inserted ' + inserted);
}

// Deliberately SEPARATE single-field indexes: a compound {a:1,b:1} would answer the query
// outright and there would be no ranking decision to make.
print('creating indexes {a:1} and {b:1}');
c.createIndex({ a: 1 }, { name: 'a_1' });
c.createIndex({ b: 1 }, { name: 'b_1' });

const st = c.stats();
CH.emit({
  kind: 'w4_build', db: DB, coll: COLL, mirror: MIRROR,
  n: c.countDocuments({}), n_poison: M0, n_match: M, n_tail: N - M1,
  matches_verified: c.countDocuments({ a: 1, b: 5 }),
  good_prefix_plan: goodPrefix,
  // Documents each plan must examine to run to completion -- the ground truth the trial
  // period is supposed to be approximating.
  truth_a_docs_examined: cost['ixscan:a_1'], truth_b_docs_examined: cost['ixscan:b_1'],
  truth_ratio: cost[goodPrefix] / Math.min(cost['ixscan:a_1'], cost['ixscan:b_1']),
  size_bytes: st.size, storage_bytes: st.storageSize, index_bytes: st.totalIndexSize,
});

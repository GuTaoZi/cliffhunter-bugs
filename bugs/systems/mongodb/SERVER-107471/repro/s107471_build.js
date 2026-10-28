// SERVER-107471 dataset -- "Query Plan Cache Issue with Index Selection on High Disparity
// Index Values" (reported 2025-07-14, closed Won't Do, 5 watchers, no comments).
//
// The report, in the reporter's own words:
//   "regardless of whether skip is included or not, both queries generate the same
//    queryHash and planCacheKey. However, the cached plan that incorporates a skip
//    condition could lead to very inefficient query plans when the query value has a high
//    disparity (e.g. {"indexField10": NumberLong(93333)}) without a skip condition, which
//    retrieves only a single document."
//
// Two ingredients, both named in the ticket, and this file builds both:
//
//   (1) HIGH DISPARITY on one indexed field. indexField10 takes the value 0 on ~98% of the
//       collection and a unique value on 1 000 documents. So one parameter class of the
//       same shape wants IXSCAN{indexField10} (1 key) and another wants
//       IXSCAN{indexField1} (N_HOT keys), and getting it wrong costs N_HOT x.
//
//   (2) A SKIP that is invisible to the plan cache key. Verified separately in
//       s107471_order.js rather than assumed: on 8.2.12 neither skip nor limit is encoded
//       in planCacheKey/queryHash, so find(F,P).skip(S).limit(L) and find(F,P).limit(L)
//       are ONE cache entry.
//
// Why the skip matters mechanically, which is the part the ticket does not spell out: the
// multi-planner's trial-period result target is min(101, limit) and does NOT account for
// skip (multi_plan.cpp getTrialPeriodNumToReturn). A SKIP stage sits under the LIMIT, so
// every skipped document costs a work unit and yields no result. decisionWorks for the
// winning plan therefore grows by ~S -- and decisionWorks is exactly the replan bar
// divided by internalQueryCacheEvictionRatio (10.0). One .skip(5000) in the workload
// raises the replan bar to ~50 000 reads for EVERY query of the shape, including queries
// that have no skip at all. Any wrong plan costing less than that becomes uncorrectable.
//
// Sizing rule, stated up front so it can be checked rather than tuned in secret:
//     immunity requires   10 x S   >   N_HOT   (the cost of the wrong plan, in reads)
// Defaults give 10 x 5 000 = 50 000 > 20 000, a margin of 2.5x.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB      = CH.env('S1_DB', 'ch_s107471');
const COLL    = CH.env('S1_COLL', 'docs');
const N       = CH.envInt('S1_N', 1000000);
const F1_HOT  = CH.envInt('S1_F1_HOT', 7);        // the value class P and class R share
const N_HOT   = CH.envInt('S1_N_HOT', 20000);     // docs with indexField1 = F1_HOT
const N_RARE  = CH.envInt('S1_N_RARE', 1000);     // distinct high-disparity indexField10 values
const RARE_B  = CH.envInt('S1_RARE_BASE', 93333); // the ticket's own literal
const BATCH   = CH.envInt('S1_BATCH', 20000);
const PADLEN  = CH.envInt('S1_PADLEN', 64);

const d = db.getSiblingDB(DB);
const c = d.getCollection(COLL);
c.drop();

const pad = 'x'.repeat(PADLEN);
const nHotCommon = N_HOT - N_RARE;                // indexField1=7, indexField10=0
const nCold      = N - N_HOT;                     // indexField1 != 7, indexField10=0
if (nHotCommon <= 0 || nCold <= 0) throw new Error('N too small for the requested classes');

// Interleaved so no class is clustered at one end: W4 showed recordId position alone can
// decide a plan, and this experiment must not accidentally re-run W4.
function* docs() {
  let id = 0;
  const coldPerRare = Math.floor(nCold / N_RARE);
  const hotPerRare  = Math.floor(nHotCommon / N_RARE);
  for (let k = 0; k < N_RARE; k++) {
    yield { _id: id++, indexField1: F1_HOT, indexField10: RARE_B + k, pad: pad };
    for (let j = 0; j < hotPerRare; j++)
      yield { _id: id++, indexField1: F1_HOT, indexField10: 0, pad: pad };
    for (let j = 0; j < coldPerRare; j++)
      yield { _id: id++, indexField1: 10 + (id % 9), indexField10: 0, pad: pad };
  }
  while (id < N) yield { _id: id++, indexField1: 10 + (id % 9), indexField10: 0, pad: pad };
}

print('building ' + N + ' docs into ' + DB + '.' + COLL);
let batch = [], inserted = 0;
for (const doc of docs()) {
  batch.push(doc);
  if (batch.length === BATCH) {
    c.insertMany(batch, { ordered: false }); inserted += batch.length; batch = [];
    if (inserted % (BATCH * 25) === 0) print('  inserted ' + inserted);
  }
}
if (batch.length) { c.insertMany(batch, { ordered: false }); inserted += batch.length; }

print('creating indexes {indexField1:1} and {indexField10:1}');
c.createIndex({ indexField1: 1 },  { name: 'indexField1_1' });
c.createIndex({ indexField10: 1 }, { name: 'indexField10_1' });

const hot   = c.countDocuments({ indexField1: F1_HOT });
const if10z = c.countDocuments({ indexField10: 0 });
const pMatch = c.countDocuments({ indexField1: F1_HOT, indexField10: 0 });
const rMatch = c.countDocuments({ indexField1: F1_HOT, indexField10: RARE_B });
const st = c.stats();
CH.emit({
  kind: 's107471_build', db: DB, coll: COLL, n: inserted,
  f1_hot: F1_HOT, n_hot: hot, if10_zero: if10z, n_rare: N_RARE, rare_base: RARE_B,
  p_match: pMatch, r_match: rMatch,
  disparity: if10z / Math.max(rMatch, 1),      // 'high disparity index values', quantified
  wrong_plan_ratio: hot / Math.max(rMatch, 1), // cost of using indexField1 for class R
  size_bytes: st.size, storage_bytes: st.storageSize, index_bytes: st.totalIndexSize,
});

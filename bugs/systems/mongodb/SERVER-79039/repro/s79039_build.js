// SERVER-79039 dataset -- "Plan cache entries can be evicted and replanned continuously
// for certain workload patterns" (reported 2023-07-17, closed Won't Do, 10 watchers).
//
// The reporter's mechanism, verbatim:
//   "For certain patterns of queries, we can run into a cycle of cache->evict->replan->
//    cache for the same query shape AND SAME PLAN depending on the parameters. By default
//    the planner requires a 10x increase in works to trigger replanning... However, when
//    the higher work plan triggers the eviction, the cache entry remains in an 'inactive'
//    state. If the next query to activate it has a lower works value, then we'll use the
//    new one. This puts us in a state where its like the higher work query never
//    happened, and its possible to evict and replan again."
//
// "same plan" is the sharp part and this build targets it: both parameter classes want
// IXSCAN{a}, so every replan re-derives the plan it already had. That is pure waste, and
// 8.2 counts it -- metrics.query.planCache.classic.replanned_plan_is_cached_plan, added
// by SERVER-98987 in 8.2.0. MongoDB instrumented the symptom in the same release it
// declined to fix.
//
// One query SHAPE, find({a:<int>, b:0}), two parameter classes:
//   C ("cheap")      a = 1..NCHEAP     5 docs, all with b=0
//                      IXSCAN{a}: 5 keys, 5 results, EOF at ~6 works.
//   E ("expensive")  a = EVAL          N_E docs, only 3 with b=0
//                      IXSCAN{a}: N_E keys, 3 results, EOF at ~N_E works.
// Both prefer IXSCAN{a} -- E is not a wrong-plan victim, it is a legitimately expensive
// instance of the same shape. Nothing here is a mis-estimate; the defect is entirely in
// the hysteretic state.
//
// Sizing rule, stated so it can be checked rather than tuned in secret:
//     thrash requires   N_E  >  10 x W_cheap (~= 60).
// The default N_E = 50 000 clears that by ~800x, so the effect is not sitting on a knife
// edge; harness/s79039_order.js sweeps N_E to locate the actual boundary.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB      = CH.env('S2_DB', 'ch_s79039');
const COLL    = CH.env('S2_COLL', 'docs');
const N       = CH.envInt('S2_N', 1000000);
const NCHEAP  = CH.envInt('S2_NCHEAP', 1000);    // distinct cheap 'a' values
const PERCHP  = CH.envInt('S2_PER_CHEAP', 5);    // docs per cheap value (< 101, see W4)
const EVAL    = CH.envInt('S2_EVAL', 900001);    // the expensive 'a' value
const N_E     = CH.envInt('S2_N_E', 50000);      // docs at a = EVAL
const E_HITS  = CH.envInt('S2_E_HITS', 3);       // of those, how many have b = 0
const BATCH   = CH.envInt('S2_BATCH', 20000);
const PADLEN  = CH.envInt('S2_PADLEN', 64);

const d = db.getSiblingDB(DB);
const c = d.getCollection(COLL);
c.drop();

const pad = 'x'.repeat(PADLEN);
const nFiller = N - NCHEAP * PERCHP - N_E;
if (nFiller <= 0) throw new Error('N too small for the requested classes');

// Interleaved, so neither class is clustered at one end of the recordId space (W4).
function* docs() {
  let id = 0;
  const fillerPerStep = Math.floor(nFiller / NCHEAP);
  const ePerStep = Math.floor(N_E / NCHEAP);
  let eEmitted = 0;
  for (let v = 1; v <= NCHEAP; v++) {
    for (let k = 0; k < PERCHP; k++) yield { _id: id++, a: v, b: 0, pad: pad };
    for (let k = 0; k < ePerStep; k++) {
      // Only the first E_HITS documents of class E have b = 0, so the E query returns
      // E_HITS results after reading all N_E of them: high works, tiny result set.
      yield { _id: id++, a: EVAL, b: (eEmitted++ < E_HITS ? 0 : 1), pad: pad };
    }
    for (let k = 0; k < fillerPerStep; k++) yield { _id: id++, a: 0, b: 0, pad: pad };
  }
  while (eEmitted < N_E) { yield { _id: id++, a: EVAL, b: (eEmitted++ < E_HITS ? 0 : 1), pad: pad }; }
  while (id < N) yield { _id: id++, a: 0, b: 0, pad: pad };
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

print('creating indexes {a:1} and {b:1}');
c.createIndex({ a: 1 }, { name: 'a_1' });
c.createIndex({ b: 1 }, { name: 'b_1' });

const st = c.stats();
CH.emit({
  kind: 's79039_build', db: DB, coll: COLL, n: inserted,
  ncheap: NCHEAP, per_cheap: PERCHP, eval_a: EVAL, n_e: c.countDocuments({ a: EVAL }),
  e_hits: c.countDocuments({ a: EVAL, b: 0 }),
  c_hits: c.countDocuments({ a: 1, b: 0 }),
  b0_count: c.countDocuments({ b: 0 }),
  works_ratio: N_E / Math.max(PERCHP + 1, 1),   // E's works / C's works, the thrash driver
  size_bytes: st.size, storage_bytes: st.storageSize, index_bytes: st.totalIndexSize,
});

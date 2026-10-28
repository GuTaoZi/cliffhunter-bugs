// W5 dataset: the plan-cache works ratchet, probed by ORDER (oracle O3).
//
// One query SHAPE, find({a:<int>, b:<int>}), so every query shares one plan cache entry
// (the key is the shape, not the values). Two parameter CLASSES that want opposite plans,
// and each of which is catastrophic under the other's plan:
//
//   E ("easy on a")  find({a: i,  b: 0})   i in 1..NRARE
//        plan {a:1}: scans a=i          -> ~PER_RARE keys       CHEAP
//        plan {b:1}: scans b=0          -> ~980 000 docs        CATASTROPHIC
//   H ("hard on a")  find({a: 0,  b: j})   j in 1..NRARE
//        plan {b:1}: scans b=j          -> ~PER_RARE keys       CHEAP
//        plan {a:1}: scans a=0          -> ~980 000 docs        CATASTROPHIC
//
// Layout: a=0 and b=0 are both COMMON; every other value of a and of b is RARE.
//   [filler]    {a:0, b:0}          the bulk, matches NEITHER class
//   [E-targets] {a:i, b:0}          PER_RARE docs for each i in 1..NRARE
//   [H-targets] {a:0, b:j}          PER_RARE docs for each j in 1..NRARE
//
// Both classes return PER_RARE (20) documents, deliberately BELOW the 101-result trial
// bound: W4 showed that a cached plan producing 101 results ends its trial with
// '_bestPlanChosen = true' and can never replan (cached_plan.cpp:122-126). Keeping result
// sets small is what lets the replanning machinery actually engage, which is what W5 tests.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB       = CH.env('W5_DB', 'w5');
const COLL     = CH.env('W5_COLL', 'docs');
// W5_MEDIUM=1 adds a third parameter class M to the same query shape. M exists to set the
// replan BAR high: the replan threshold is internalQueryCacheEvictionRatio (10.0) x
// decisionWorks, and decisionWorks comes from whichever instance's multi-planning promoted
// the cache entry to active. An M instance legitimately costs ~200 000 works, so if M
// promotes the entry the bar becomes ~2 000 000 -- larger than the collection -- and a bad
// plan for E or H can then never trip it. Whether M promotes first is purely an ORDER
// question, which is exactly what O3 tests.
//   M  find({a: MA, b: MB})  ->  5 results; both plans must scan ~200 000 keys
const MEDIUM   = CH.envInt('W5_MEDIUM', 0) === 1;
const MA       = CH.envInt('W5_MA', 9001);      // medium-cardinality value of a
const MB       = CH.envInt('W5_MB', 9002);      // medium-cardinality value of b
const NMED     = CH.envInt('W5_NMED', 200000);  // docs per medium value
const NMEDHIT  = CH.envInt('W5_NMEDHIT', 5);    // a=MA AND b=MB  (>0: a zero-result winner
                                                // is refused by the plan cache entirely)
const N        = CH.envInt('W5_N', 1000000);
const NRARE    = CH.envInt('W5_NRARE', 1000);   // distinct rare values per field
const PER_RARE = CH.envInt('W5_PER_RARE', 20);  // docs per rare value  (< 101, see above)
const BATCH    = CH.envInt('W5_BATCH', 20000);
const PADLEN   = CH.envInt('W5_PADLEN', 64);

const d = db.getSiblingDB(DB);
const c = d.getCollection(COLL);
c.drop();

const pad = 'x'.repeat(PADLEN);
const nTargets = NRARE * PER_RARE;              // per class
const nMedium  = MEDIUM ? 2 * NMED - NMEDHIT : 0;
const nFiller  = N - 2 * nTargets - nMedium;
if (nFiller <= 0) throw new Error('N too small for the requested classes');

// Emitted in one interleaved pass so neither class is clustered at one end of the
// collection: W4 showed that recordId position alone can decide a plan, and W5 must not
// accidentally re-run W4. Filler is spread evenly between the target documents.
function* docs() {
  let id = 0;
  const fillerPerStep = Math.floor(nFiller / (2 * NRARE));
  for (let v = 1; v <= NRARE; v++) {
    for (let k = 0; k < PER_RARE; k++) yield { _id: id++, a: v, b: 0, pad: pad };   // E-target
    for (let k = 0; k < fillerPerStep; k++) yield { _id: id++, a: 0, b: 0, pad: pad };
    for (let k = 0; k < PER_RARE; k++) yield { _id: id++, a: 0, b: v, pad: pad };   // H-target
    for (let k = 0; k < fillerPerStep; k++) yield { _id: id++, a: 0, b: 0, pad: pad };
  }
  if (MEDIUM) {
    // a=MA and b=MB each reach NMED documents, but their intersection is only NMEDHIT,
    // so both candidate plans must scan ~NMED keys to return NMEDHIT results. That is a
    // legitimately expensive instance of the same shape -- not a defect, which is the
    // point: it sets a high bar honestly.
    for (let k = 0; k < NMEDHIT; k++)          yield { _id: id++, a: MA, b: MB, pad: pad };
    for (let k = 0; k < NMED - NMEDHIT; k++)   yield { _id: id++, a: MA, b: 0,  pad: pad };
    for (let k = 0; k < NMED - NMEDHIT; k++)   yield { _id: id++, a: 0,  b: MB, pad: pad };
  }
  while (id < N) yield { _id: id++, a: 0, b: 0, pad: pad };                          // remainder
}

print('building ' + N + ' docs into ' + DB + '.' + COLL
      + ' (' + NRARE + ' rare values x ' + PER_RARE + ' docs per class, filler ' + nFiller + ')');
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

const aCommon = c.countDocuments({ a: 0 });
const bCommon = c.countDocuments({ b: 0 });
const st = c.stats();
CH.emit({
  kind: 'w5_build', db: DB, coll: COLL, n: inserted, nrare: NRARE, per_rare: PER_RARE,
  medium: MEDIUM, a0_count: aCommon, b0_count: bCommon,
  ma_count: MEDIUM ? c.countDocuments({ a: MA }) : null,
  mb_count: MEDIUM ? c.countDocuments({ b: MB }) : null,
  m_match: MEDIUM ? c.countDocuments({ a: MA, b: MB }) : null,
  e_match: c.countDocuments({ a: 1, b: 0 }), h_match: c.countDocuments({ a: 0, b: 1 }),
  // The cost of getting the plan wrong, per query, in documents examined.
  wrong_plan_ratio: aCommon / PER_RARE,
  size_bytes: st.size, storage_bytes: st.storageSize, index_bytes: st.totalIndexSize,
});

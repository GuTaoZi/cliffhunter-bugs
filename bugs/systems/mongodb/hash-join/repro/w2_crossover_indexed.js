// Does an index on the foreign join field move the hash-vs-nested-loop crossover?
//
// Without an index, nested loop costs ~ local x foreign (a full scan per local document),
// so it only wins for a handful of local documents. WITH an index it becomes an INDEXED
// nested loop, ~ local x log(foreign), which should beat hash join's fixed build cost over
// a far wider range -- predicted crossover near local ~ foreign/log2(foreign) ~ 750.
//
// This matters because isEligibleForHashJoin() checks neither the local size NOR whether a
// foreign index exists, so it cannot distinguish these two very different situations.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB      = CH.env('W2_DB', 'w2');
const FOREIGN = CH.env('XI_FOREIGN', 'foreign_10000');
const REPS    = CH.envInt('XI_REPS', 5);
const SIZES   = CH.env('XI_LOCALS', '1,5,25,100,250,500,1000,2000')
                  .split(',').map((s) => parseInt(s.trim(), 10));

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeEngine' });

for (const L of SIZES) {
  const name = 'xlocal_' + L;
  if (d[name].countDocuments({}) !== L) {
    d[name].drop();
    const b = []; for (let i = 0; i < L; i++) b.push({ _id: i, f: i % 10000 });
    d[name].insertMany(b, { ordered: false });
  }
}

function pipeline(local, foreign) {
  return [{ $lookup: { from: foreign, localField: 'f', foreignField: 'g', as: 'out' } },
          { $group: { _id: null, t: { $sum: { $size: '$out' } } } }];
}

function measure(L, knob) {
  db.adminCommand({ setParameter: 1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin: knob });
  const local = 'xlocal_' + L;
  const ex = d[local].explain('executionStats').aggregate(pipeline(local, FOREIGN));
  const algo = CH.joinAlgo(ex);
  d[local].aggregate(pipeline(local, FOREIGN)).toArray();
  const s = [];
  for (let i = 0; i < REPS; i++) s.push(CH.timeNs(() => d[local].aggregate(pipeline(local, FOREIGN)).toArray()));
  return { algo: algo, ms: CH.stats(s).median_ms };
}

for (const indexed of [false, true]) {
  if (indexed) { d[FOREIGN].createIndex({ g: 1 }); print('created index on ' + FOREIGN + '.g'); }
  else { try { d[FOREIGN].dropIndex({ g: 1 }); } catch (e) { /* not present */ } }
  for (const L of SIZES) {
    const hash = measure(L, 1000000);
    const nl   = measure(L, 1);
    CH.emit({ kind: 'xi_point', foreign_indexed: indexed, local_docs: L,
              hash_algo: hash.algo, hash_ms: hash.ms, nl_algo: nl.algo, nl_ms: nl.ms });
  }
}
try { d[FOREIGN].dropIndex({ g: 1 }); } catch (e) { /* ignore */ }
db.adminCommand({ setParameter: 1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin: 10000 });
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });

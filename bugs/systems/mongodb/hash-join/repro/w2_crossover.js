// Where, if anywhere, does nested loop actually BEAT hash join?
//
// If no such regime exists, the eligibility gate is pure loss and should be deleted rather
// than retuned. If one does exist, we learn the variable the gate SHOULD have keyed on.
//
// Theory: hash join costs ~ (foreign + local) -- it must build a table over the whole
// foreign collection before probing. Nested loop costs ~ (local x foreign). So nested loop
// can only win when `local` is small enough that building the table never amortises.
// Note that `local` is exactly the variable isEligibleForHashJoin() never looks at.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB      = CH.env('W2_DB', 'w2');
const FOREIGN = CH.env('XO_FOREIGN', 'foreign_10000');
const REPS    = CH.envInt('XO_REPS', 5);
const SIZES   = CH.env('XO_LOCALS', '1,2,5,10,25,50,100,250,500,1000,2000')
                  .split(',').map((s) => parseInt(s.trim(), 10));

const d = db.getSiblingDB(DB);
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeEngine' });

// Build local collections of each size.
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
  // knob=1 forces nested loop (foreign has 10000 records > 1); a large knob allows hash.
  db.adminCommand({ setParameter: 1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin: knob });
  const local = 'xlocal_' + L;
  const ex = d[local].explain('executionStats').aggregate(pipeline(local, FOREIGN));
  const facts = CH.planFacts(ex);
  const algo = CH.joinAlgo(ex);
  d[local].aggregate(pipeline(local, FOREIGN)).toArray();                    // warm
  const s = [];
  for (let i = 0; i < REPS; i++) s.push(CH.timeNs(() => d[local].aggregate(pipeline(local, FOREIGN)).toArray()));
  return { algo: algo, docs: facts.totalDocsExamined, lat: CH.stats(s) };
}

for (const L of SIZES) {
  const hash = measure(L, 1000000);
  const nl   = measure(L, 1);
  CH.emit({ kind: 'xo_point', local_docs: L, foreign: FOREIGN,
            hash_algo: hash.algo, hash_docs: hash.docs, hash_ms: hash.lat.median_ms,
            nl_algo: nl.algo,   nl_docs: nl.docs,     nl_ms: nl.lat.median_ms });
}
db.adminCommand({ setParameter: 1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin: 10000 });
db.adminCommand({ setParameter: 1, internalQueryFrameworkControl: 'trySbeRestricted' });

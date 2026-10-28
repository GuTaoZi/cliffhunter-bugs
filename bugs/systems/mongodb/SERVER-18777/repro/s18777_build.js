// SERVER-18777 dataset: W5's layout (works-ratchet/repro/w5_build.js) plus a unique field c for the second branch
// of a rooted $or. Per step v = 1..NRARE, 300 documents in this order:
//   20 {a: v, b: 0}   (class A's targets)      130 {a: 0, b: 0} (filler)
//   20 {a: 0, b: v}   (class B's targets)      130 {a: 0, b: 0} (filler)
// so a = 0 and b = 0 each match 280 documents per step: 280,000 at NRARE = 1000. Class A, {a: i, b: 0}, is 20
// documents under IXSCAN{a} and 280,000 under IXSCAN{b}; class B, {a: 0, b: j}, the mirror image. c is the
// document's running id (unique), so the $or's second branch {c: K} matches one document through c_1.
load((typeof process !== 'undefined' && process.env.CH_LIB) ||
     (typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB = CH.env('S3_DB', 'ch_s18777');
const COLL = CH.env('S3_COLL', 'orq');
const NRARE = CH.envInt('S3_NRARE', 1000);
const PER = CH.envInt('S3_PER_RARE', 20);
const FILL = CH.envInt('S3_FILL', 130);

const d = db.getSiblingDB(DB);
d.getCollection(COLL).drop();
const coll = d.getCollection(COLL);
const pad = 'x'.repeat(64);
let id = 0, batch = [];
const push = (a, b) => {
  batch.push({ _id: id, a: a, b: b, c: id, pad: pad });
  id++;
  if (batch.length >= 10000) { coll.insertMany(batch, { ordered: false }); batch = []; }
};
const t0 = Date.now();
for (let v = 1; v <= NRARE; v++) {
  for (let i = 0; i < PER; i++) push(v, 0);
  for (let i = 0; i < FILL; i++) push(0, 0);
  for (let i = 0; i < PER; i++) push(0, v);
  for (let i = 0; i < FILL; i++) push(0, 0);
}
if (batch.length) coll.insertMany(batch, { ordered: false });
coll.createIndex({ a: 1 });
coll.createIndex({ b: 1 });
coll.createIndex({ c: 1 });
CH.emit({ kind: 's18777_build', db: DB, coll: COLL, docs: coll.estimatedDocumentCount(),
          a0: coll.countDocuments({ a: 0 }), b0: coll.countDocuments({ b: 0 }),
          first_filler_c: PER, build_ms: Date.now() - t0 });

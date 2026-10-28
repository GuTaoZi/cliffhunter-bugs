// W2 dataset: $lookup hash-join eligibility cliff.
// isEligibleForHashJoin() consults ONLY foreign-collection stats:
//   noOfRecords <= internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin (10000)
//   approximateDataSizeBytes <= ...MaxDataSizeBytes... (100MB)
//   storageSizeBytes <= ...MaxStorageSizeBytes... (100MB)
// It never consults the number of LOCAL driving documents, nor whether a usable
// index exists on the foreign field. So we build foreign collections that straddle
// 10000 by a single document, with no index on the join field.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W2_DB', 'w2');
const LOCAL  = CH.envInt('W2_LOCAL', 2000);
const SIZES  = CH.env('W2_SIZES', '9998,9999,10000,10001,10002,10010')
                 .split(',').map((s) => parseInt(s.trim(), 10));
const PADLEN = CH.envInt('W2_PADLEN', 32);
const NKEYS  = CH.envInt('W2_NKEYS', 10000);   // join-key domain

const d = db.getSiblingDB(DB);
const pad = 'y'.repeat(PADLEN);

d.local.drop();
const lbatch = [];
for (let i = 0; i < LOCAL; i++) lbatch.push({ _id: i, f: i % NKEYS, pad: pad });
d.local.insertMany(lbatch, { ordered: false });
print('local: ' + d.local.countDocuments({}) + ' docs');

const built = [];
for (const size of SIZES) {
  const name = 'foreign_' + size;
  d[name].drop();
  let inserted = 0;
  while (inserted < size) {
    const batch = [];
    const upto = Math.min(20000, size - inserted);
    for (let j = 0; j < upto; j++) {
      const i = inserted + j;
      batch.push({ _id: i, g: i % NKEYS, pad: pad });
    }
    d[name].insertMany(batch, { ordered: false });
    inserted += upto;
  }
  // Deliberately NO index on g -- that is the point: the heuristic never checks.
  const st = d[name].stats();
  built.push({ name: name, n: d[name].countDocuments({}), size_bytes: st.size,
               storage_bytes: st.storageSize, indexes: Object.keys(st.indexSizes || {}) });
}

CH.emit({ kind: 'w2_build', db: DB, local: d.local.countDocuments({}), nkeys: NKEYS, foreign: built });

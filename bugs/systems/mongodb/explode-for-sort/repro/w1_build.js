// W1 dataset: explode-for-sort cliff (internalQueryMaxScansToExplode = 200).
// Compound index {tag:1, ts:1}; $in on the leading field, sort on the trailing one.
load((typeof __dirname !== 'undefined' ? __dirname + '/' : '') + '../../../../../tools/harness/lib.js');

const DB     = CH.env('W1_DB', 'w1');
const N      = CH.envInt('W1_N', 2000000);
const NTAGS  = CH.envInt('W1_NTAGS', 400);
const BATCH  = CH.envInt('W1_BATCH', 20000);
const PADLEN = CH.envInt('W1_PADLEN', 64);

const d = db.getSiblingDB(DB);
d.docs.drop();

const pad = 'x'.repeat(PADLEN);
// Deterministic LCG so ts ordering is reproducible and uncorrelated with insertion order.
let seed = 12345;
function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed; }

print('building ' + N + ' docs across ' + NTAGS + ' tags into ' + DB + '.docs');
let inserted = 0;
while (inserted < N) {
  const batch = [];
  const upto = Math.min(BATCH, N - inserted);
  for (let j = 0; j < upto; j++) {
    const i = inserted + j;
    batch.push({ _id: i, tag: i % NTAGS, ts: rnd(), pad: pad });
  }
  d.docs.insertMany(batch, { ordered: false });
  inserted += upto;
  if (inserted % (BATCH * 20) === 0) print('  inserted ' + inserted);
}

print('creating index {tag:1, ts:1}');
d.docs.createIndex({ tag: 1, ts: 1 });

const st = d.docs.stats();
CH.emit({
  kind: 'w1_build', db: DB, n: d.docs.countDocuments({}), ntags: NTAGS,
  docs_per_tag: N / NTAGS,
  size_bytes: st.size, storage_bytes: st.storageSize, index_bytes: st.totalIndexSize,
});

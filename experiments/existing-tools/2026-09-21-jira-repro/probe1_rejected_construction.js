// Exploratory: does .skip() change which plan multi-planning picks, holding the query fixed?
const d = db.getSiblingDB('ch_probe');
const c = d.getCollection('e1');
c.drop();
const N = 300000;
const pad = 'x'.repeat(64);
let batch = [];
for (let i = 0; i < N; i++) {
  // cat: 0 is common (99%), others rare; ts: unique-ish ordering key
  const rare = (i % 1000 === 0);
  batch.push({ _id: i, cat: rare ? (1000 + (i/1000)) : 0, ts: i, pad: pad });
  if (batch.length === 20000) { c.insertMany(batch, {ordered:false}); batch = []; }
}
if (batch.length) c.insertMany(batch, {ordered:false});
c.createIndex({cat:1}); c.createIndex({ts:-1}); 
print('built ' + c.countDocuments({}) + ' docs; cat=0 -> ' + c.countDocuments({cat:0}) + '; cat=1001 -> ' + c.countDocuments({cat:1001}));

function probe(label, cur) {
  c.getPlanCache().clear();
  const e = cur.explain('executionStats');
  const qp = e.queryPlanner, ex = e.executionStats;
  const w = JSON.stringify(qp.winningPlan);
  const idx = (w.match(/"indexName":"([^"]+)"/) || [null,'COLLSCAN'])[1];
  const hasSort = w.indexOf('"stage":"SORT"') !== -1;
  // works of the winner during the trial
  const rej = (e.queryPlanner.rejectedPlans||[]).map(p => (JSON.stringify(p).match(/"indexName":"([^"]+)"/)||[null,'COLLSCAN'])[1]);
  print(label.padEnd(46) + ' key=' + qp.planCacheKey + ' WIN=' + idx + (hasSort?'+SORT':'') 
        + ' rej=[' + rej.join(',') + ']'
        + ' docs=' + ex.totalDocsExamined + ' keys=' + ex.totalKeysExamined + ' n=' + ex.nReturned + ' ms=' + ex.executionTimeMillis);
}
for (const catv of [0, 1001]) {
  print('--- cat=' + catv + ' (sort ts desc, limit 10) ---');
  probe('sort(ts:-1).limit(10)             cat='+catv, c.find({cat:catv}).sort({ts:-1}).limit(10));
  probe('sort(ts:-1).skip(1000).limit(10)  cat='+catv, c.find({cat:catv}).sort({ts:-1}).skip(1000).limit(10));
  probe('sort(ts:-1).skip(10000).limit(10) cat='+catv, c.find({cat:catv}).sort({ts:-1}).skip(10000).limit(10));
  print('--- cat=' + catv + ' (no sort) ---');
  probe('limit(10)                         cat='+catv, c.find({cat:catv}).limit(10));
  probe('skip(1000).limit(10)              cat='+catv, c.find({cat:catv}).skip(1000).limit(10));
}

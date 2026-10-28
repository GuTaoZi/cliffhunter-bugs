const d = db.getSiblingDB('ch_probe');
const c = d.getCollection('p');
c.drop();
const docs = [];
for (let i = 0; i < 20000; i++) {
  docs.push({ _id: i, f1: i % 10, f10: (i < 19900 ? 0 : i), pad: 'x'.repeat(32) });
}
c.insertMany(docs, {ordered:false});
c.createIndex({f1:1}); c.createIndex({f10:1});
const q = {f1: 3, f10: 0};
const proj = {f1:1, f10:1, _id:0};
function key(label, cur) {
  const e = cur.explain();
  const qp = e.queryPlanner;
  print(label.padEnd(34) + ' planCacheKey=' + qp.planCacheKey + '  queryHash=' + qp.queryHash
        + '  winner=' + JSON.stringify(qp.winningPlan).slice(0,90));
}
key('find(q)',                 c.find(q));
key('find(q).skip(100)',       c.find(q).skip(100));
key('find(q).limit(10)',       c.find(q).limit(10));
key('find(q).skip(100).limit(10)', c.find(q).skip(100).limit(10));
key('find(q,proj).limit(10)',  c.find(q, proj).limit(10));
key('find(q,proj).skip(100).limit(10)', c.find(q, proj).skip(100).limit(10));
key('find(q).sort({f1:1})',    c.find(q).sort({f1:1}));
key('find(q).sort({f1:1}).skip(100)', c.find(q).sort({f1:1}).skip(100));

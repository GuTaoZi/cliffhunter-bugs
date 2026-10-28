// Is the knob a FIX, or a goalpost the workload can walk past?
//
// Measuring the knob against a FIXED workload says it recovers 100% of the headroom: raising
// internalQueryPlanEvaluationMaxResults from 101 to 202 takes W4 from 2,950,000 documents
// examined to 50,101, which is exactly what forcing the right plan achieves. That number is
// true and it is the wrong question.
//
// The trial period fills its batch with matches, so the plan that LOOKS productive is the one
// whose matches are front-loaded. What decides the outcome is the MATCH COUNT versus the knob,
// and the match count is a property of the data. So for any setting there is a collection just
// past it. This runs the matrix and shows the cliff moving rather than closing.
//
//   mongosh --quiet --port "$CH_PORT" harness/knob_goalpost.js
const admin = db.getSiblingDB("admin");
const w4 = db.getSiblingDB("w4");
const KNOB = "internalQueryPlanEvaluationMaxResults";
const stock = admin.runCommand({getParameter: 1, [KNOB]: 1})[KNOB];

const COLLS = [["docs", 101], ["docs_k1000", 1000]];
const KNOBS = [101, 202, 1010, 5050];

function docsExamined(coll) {
  return w4[coll].find({a: 1, b: 5}).explain("executionStats")
          .executionStats.totalDocsExamined;
}
function optimum(coll) {
  return w4[coll].find({a: 1, b: 5}).hint({b: 1}).explain("executionStats")
          .executionStats.totalDocsExamined;
}

const opt = {};
for (const [c] of COLLS) opt[c] = optimum(c);

print("documents examined; the forced optimum is in brackets\n");
let hdr = "knob".padStart(7);
for (const [c, m] of COLLS) hdr += `   ${(c + " (" + m + " matches)").padStart(26)}`;
print(hdr);
const rows = [];
for (const k of KNOBS) {
  admin.runCommand({setParameter: 1, [KNOB]: k});
  let line = String(k).padStart(7);
  const row = {knob: k};
  for (const [c, m] of COLLS) {
    const d = docsExamined(c);
    row[c] = d;
    const bad = d > opt[c] * 2;
    line += `   ${((bad ? "CLIFF " : "ok    ") + d.toLocaleString()).padStart(26)}`;
  }
  rows.push(row);
  print(line);
}
admin.runCommand({setParameter: 1, [KNOB]: stock});
let f = "optimum".padStart(7);
for (const [c] of COLLS) f += `   ${("= " + opt[c].toLocaleString()).padStart(26)}`;
print(f);
print("\nJSON " + JSON.stringify({knob: KNOB, stock, optimum: opt, rows}));

// How much of the available improvement does the vendor's OWN knob recover?
//
// Every knob experiment we have done so far answered this for one site at a time, in its own
// units, and concluded "the knob does not help". That is eleven anecdotes. This measures the
// same quantity the same way across several sites so the answer is a distribution:
//
//     optimization rate  =  (stock - best knob setting) / (stock - forced optimum)
//
//   1.0  the knob fully recovers what a correct decision would have achieved
//   0.0  the knob recovers nothing; the defect is not in the constant
//   <0   tuning the knob makes it worse
//
// `stock` is the shipped default. `optimum` is the cost when the right decision is FORCED
// (a hint, or the algorithm chosen directly) -- the headroom a perfect heuristic would get.
// Running every arm on one server, sequentially, on purpose: parallel arms on one mongod
// contend for the same WiredTiger cache and the timings stop meaning anything.
//
//   mongosh --quiet --port "$CH_PORT" harness/knob_rate.js
//   SITES=w4 mongosh --quiet --port "$CH_PORT" harness/knob_rate.js

const REPS = parseInt(process.env.REPS || "5", 10);
const admin = db.getSiblingDB("admin");

function setKnob(name, value) {
  const c = {setParameter: 1};
  c[name] = value;
  const r = admin.runCommand(c);
  if (!r.ok) throw new Error(`setParameter ${name}=${value}: ${tojson(r)}`);
}

function getKnob(name) {
  const c = {getParameter: 1};
  c[name] = 1;
  return admin.runCommand(c)[name];
}

// Deterministic work counters from explain, plus a timed run. docsExamined is the honest
// primary: it is exact, and it is what the defect inflates. Wall time is reported too
// because a reviewer will ask, but it is the noisier number.
function measure(coll, filter, opts) {
  opts = opts || {};
  let cur = () => {
    let c = coll.find(filter);
    if (opts.hint) c = c.hint(opts.hint);
    if (opts.sort) c = c.sort(opts.sort);
    if (opts.limit) c = c.limit(opts.limit);
    return c;
  };
  const ex = cur().explain("executionStats").executionStats;
  const times = [];
  for (let i = 0; i < REPS; i++) {
    const t0 = Date.now();
    cur().itcount();
    times.push(Date.now() - t0);
  }
  times.sort((a, b) => a - b);
  return {
    docs: ex.totalDocsExamined,
    keys: ex.totalKeysExamined,
    ms: times[0],                       // min: least contaminated by noise
    ms_med: times[Math.floor(times.length / 2)],
  };
}

// ---------------------------------------------------------------------------
// The sites. Each needs: the knob, its sweep, the query, and how to FORCE the
// right decision so there is a headroom to measure against.
// ---------------------------------------------------------------------------
const SITES = {
  // W4: the 101-document multi-plan trial period. The trial picks {a:1} because its first
  // 101 documents are all matches; {b:1} is 58.9x cheaper run to completion.
  w4: {
    knob: "internalQueryPlanEvaluationMaxResults",
    sweep: [101, 202, 505, 1010, 5050, 50101],
    run: (knobValue) => {
      const c = db.getSiblingDB("w4").docs;
      return measure(c, {a: 1, b: 5});
    },
    optimum: () => measure(db.getSiblingDB("w4").docs, {a: 1, b: 5}, {hint: {b: 1}}),
    note: "trial period; optimum = hint the plan the full observation prefers",
  },

  // W6 IS NOT MEASURABLE WITH THIS METRIC, and that is worth stating rather than forcing.
  // Its defect is a BREACHED GUARD, not a cost cliff: memory is estimated from one sampled
  // document, the 100 MB limit is violated, and the run is 4.2x FASTER while violating it
  // (W6's "inverted oracle sign"). There is therefore no latency headroom to recover and no
  // forced optimum to measure against -- "optimization rate" is undefined. Tuning this knob
  // means choosing a different limit, not recovering lost performance.
  //
  // So the rate metric applies to THRESHOLD-shaped defects only. Left here, disabled, so the
  // next person does not have to rediscover why.
  _w6_not_applicable: {
    knob: "internalQueryMaxBlockingSortMemoryUsageBytes",
    sweep: [104857600, 209715200, 524288000, 1073741824],
    run: (knobValue) => {
      const c = db.getSiblingDB("w6").docs_big_first;
      return measure(c, {}, {sort: {pad: 1}});
    },
    optimum: () => measure(db.getSiblingDB("w6").docs_big_first, {}, {sort: {_id: 1}}),
    note: "blocking sort guard; optimum = sort on an indexed field, no blocking sort at all",
  },
};

// ---------------------------------------------------------------------------
const want = (process.env.SITES || "w4").split(",");
const out = [];

for (const name of want) {
  const s = SITES[name];
  if (!s) { print(`  (no site ${name})`); continue; }
  const stockVal = getKnob(s.knob);
  print(`\n=== ${name}   ${s.knob}`);
  print(`    ${s.note}`);
  print(`    shipped default = ${stockVal}`);

  let stock = null;
  const arms = [];
  for (const v of s.sweep) {
    setKnob(s.knob, v);
    const m = s.run(v);
    if (v === stockVal || stock === null) stock = stock || m;
    arms.push({knob: v, ...m});
    print(`      knob=${String(v).padStart(10)}  docs=${String(m.docs).padStart(9)}  ` +
          `keys=${String(m.keys).padStart(9)}  ${String(m.ms).padStart(6)} ms`);
  }
  setKnob(s.knob, stockVal);                       // always restore
  const opt = s.optimum();
  print(`      FORCED OPTIMUM          docs=${String(opt.docs).padStart(9)}  ` +
        `keys=${String(opt.keys).padStart(9)}  ${String(opt.ms).padStart(6)} ms`);

  const best = arms.reduce((a, b) => (b.docs < a.docs ? b : a));
  const head = stock.docs - opt.docs;
  const rate = head === 0 ? null : (stock.docs - best.docs) / head;
  print(`\n    stock docs ${stock.docs}  best-knob docs ${best.docs} (at ${best.knob})  ` +
        `optimum docs ${opt.docs}`);
  print(`    headroom = ${head} docs;  knob recovers ${best.docs === stock.docs ? 0 :
        stock.docs - best.docs} docs`);
  print(`    OPTIMIZATION RATE = ${rate === null ? "n/a" : (100 * rate).toFixed(1) + "%"}`);
  out.push({site: name, knob: s.knob, stock, best, opt, rate, arms});
}

print("\n--- summary -------------------------------------------------");
print("site   knob                                          rate");
for (const r of out) {
  print(`${r.site.padEnd(6)} ${r.knob.padEnd(46)} ` +
        `${r.rate === null ? "n/a" : (100 * r.rate).toFixed(1) + "%"}`);
}
print("\nJSON " + JSON.stringify(out));

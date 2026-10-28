// Shared helpers for CliffHunter workload harnesses.
// Loaded with mongosh --eval "load('harness/lib.js')" or via load() from a script.

const CH = {};

CH.env = function (name, dflt) {
  const v = process.env[name];
  return v === undefined || v === '' ? dflt : v;
};
CH.envInt = function (name, dflt) { return parseInt(CH.env(name, String(dflt)), 10); };

// Time a thunk, returning nanoseconds. Shell round-trip is included, so this
// OVERSTATES the cheap side of a cliff and therefore UNDERSTATES cliff magnitude.
// Work counters from explain() are the noise-free primary metric; latency is secondary.
CH.timeNs = function (fn) {
  const t0 = process.hrtime.bigint();
  fn();
  return Number(process.hrtime.bigint() - t0);
};

CH.quantile = function (sorted, q) {
  if (sorted.length === 0) return null;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
};

CH.stats = function (samples) {
  const s = samples.slice().sort((a, b) => a - b);
  const mean = s.reduce((a, b) => a + b, 0) / s.length;
  const sd = Math.sqrt(s.reduce((a, b) => a + (b - mean) * (b - mean), 0) / s.length);
  return {
    n: s.length,
    min_ms: s[0] / 1e6,
    p10_ms: CH.quantile(s, 0.10) / 1e6,
    median_ms: CH.quantile(s, 0.50) / 1e6,
    p90_ms: CH.quantile(s, 0.90) / 1e6,
    max_ms: s[s.length - 1] / 1e6,
    mean_ms: mean / 1e6,
    sd_ms: sd / 1e6,
    rsd: mean > 0 ? sd / mean : null,
  };
};

// Walk an explain tree collecting every stage name, root first.
CH.stageNames = function (node, acc) {
  acc = acc || [];
  if (!node || typeof node !== 'object') return acc;
  if (node.stage) acc.push(node.stage);
  if (node.nodeType) acc.push('sbe:' + node.nodeType);
  for (const key of ['inputStage', 'innerStage', 'outerStage', 'thenStage', 'elseStage']) {
    if (node[key]) CH.stageNames(node[key], acc);
  }
  for (const key of ['inputStages', 'shards']) {
    if (Array.isArray(node[key])) node[key].forEach((c) => CH.stageNames(c, acc));
  }
  return acc;
};

// Collapse runs of identical stages: 200 IXSCANs render as "IXSCAN x200".
CH.compactStages = function (stages) {
  const out = [];
  for (const s of stages) {
    const last = out[out.length - 1];
    if (last && last.name === s) last.count++;
    else out.push({ name: s, count: 1 });
  }
  return out.map((e) => (e.count > 1 ? e.name + ' x' + e.count : e.name)).join('>');
};

// Pull the fields a cliff claim needs: which plan ran, and how much work it did.
CH.planFacts = function (explain) {
  const exec = explain.executionStats || {};
  const qp = explain.queryPlanner || {};
  const winning = qp.winningPlan || {};
  const stages = CH.stageNames(winning);
  // Aggregation explains nest executionStats differently; fall back to the pipeline form.
  let docs = exec.totalDocsExamined, keys = exec.totalKeysExamined, ret = exec.nReturned;
  if (docs === undefined && explain.stages) {
    const cursor = explain.stages.find((s) => s.$cursor);
    if (cursor && cursor.$cursor.executionStats) {
      docs = cursor.$cursor.executionStats.totalDocsExamined;
      keys = cursor.$cursor.executionStats.totalKeysExamined;
    }
  }
  return {
    stages: stages,
    stage_summary: CH.compactStages(stages),
    totalDocsExamined: docs === undefined ? null : docs,
    totalKeysExamined: keys === undefined ? null : keys,
    nReturned: ret === undefined ? null : ret,
    executionTimeMillis: exec.executionTimeMillis === undefined ? null : exec.executionTimeMillis,
    usedSbe: JSON.stringify(winning).indexOf('slotBasedPlan') !== -1 || stages.some((s) => s.indexOf('sbe:') === 0),
  };
};

// Which join algorithm actually ran. Kept in ONE place: an earlier version had
// w2_sweep.js and knob_baseline.js testing different substrings, and they disagreed
// on a run where the work counters were unambiguous.
CH.joinAlgo = function (explain) {
  const blob = JSON.stringify(explain);
  const has = (s) => blob.indexOf(s) !== -1;
  if (has('HashLookup') || has('hash_lookup') || has('HashJoin')) return 'HASH_LOOKUP';
  if (has('NestedLoopJoin') || has('nlj')) return 'NESTED_LOOP';
  if (has('EQ_LOOKUP')) return 'EQ_LOOKUP_other';
  return 'UNKNOWN';
};

CH.emit = function (obj) { print('@@JSON@@' + JSON.stringify(obj)); };

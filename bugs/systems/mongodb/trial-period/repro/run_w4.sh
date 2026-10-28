#!/bin/sh
# W4 -- the 101-document trial period (internalQueryPlanEvaluationMaxResults), oracle O2.
#
# Three datasets, because the interesting claim is about the KNOB, not one workload:
#   docs         M=101  matches -- trips the default knob
#   docs_k1000   M=1000 matches -- trips a knob raised 10x  => condition (c), invariance
#   docs_mirror  M=101, the two indexes' roles swapped => is the post-cliff tie broken by
#                anything meaningful, or by candidate ordering?
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
RUN="${1:-$(date +%Y-%m-%d)-w4-trial-period}"
OUT="$ROOT/experiments/cliffs/$RUN"
mkdir -p "$OUT/raw"
CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md"

if [ "${W4_SKIP_BUILD:-0}" != "1" ]; then
  {
    W4_COLL=docs                       mongosh --quiet --port "$PORT" --file "$HERE/w4_build.js"
    W4_COLL=docs_k1000 W4_NMATCH=1000  mongosh --quiet --port "$PORT" --file "$HERE/w4_build.js"
    W4_COLL=docs_mirror W4_MIRROR=1    mongosh --quiet --port "$PORT" --file "$HERE/w4_build.js"
  } | tee "$OUT/raw/build.log"
fi

{
  W4_COLL=docs        W4_MAXRES=50,101,102,1000,100000 \
    mongosh --quiet --port "$PORT" --file "$HERE/w4_sweep.js"
  W4_COLL=docs_k1000  W4_MAXRES=101,1000,1001,100000 \
    mongosh --quiet --port "$PORT" --file "$HERE/w4_sweep.js"
  W4_COLL=docs_mirror W4_MAXRES=101,102,1000,100000 \
    mongosh --quiet --port "$PORT" --file "$HERE/w4_sweep.js"
} | tee "$OUT/raw/sweep.log"

grep -h '@@JSON@@' "$OUT"/raw/*.log | sed 's/@@JSON@@//' > "$OUT/w4.jsonl"
python3 "$HERE/w4_report.py" "$OUT/w4.jsonl" | tee "$OUT/report.txt"

# The standing requirement: CPU and peak memory, not latency alone.
RC_REPS="${RC_REPS:-5}" python3 "$HERE/w4_resource_cost.py" | tee "$OUT/resources.txt"

# Scoping: does the cost-based ranker (default from 8.3) already handle this regime?
mongosh --quiet --port "$PORT" --file "$HERE/w4_cbr_probe.js" | tee "$OUT/raw/cbr-probe.log"
grep -h '@@JSON@@' "$OUT/raw/cbr-probe.log" | sed 's/@@JSON@@//' > "$OUT/cbr.jsonl"
python3 "$HERE/w4_cbr_report.py" "$OUT/cbr.jsonl" | tee "$OUT/cbr.txt"
echo "==> results in $OUT"

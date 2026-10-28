#!/bin/sh
# W5 -- the plan-cache works ratchet, probed by arrival ORDER (oracle O3).
#
# Two collections, and the contrast between them is the result:
#   docs      E/H only: the replan bar is set by a cheap instance, so replanning works and
#             caps the damage. The control.
#   docs_bar  adds class M, a legitimately expensive instance of the SAME shape, whose
#             works value (200 001) becomes a replan bar of 2 000 010 -- bigger than the
#             collection -- so a 39 000x-wrong plan becomes immune to replanning.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
RUN="${1:-$(date +%Y-%m-%d)-w5-works-ratchet}"
OUT="$ROOT/experiments/cliffs/$RUN"
mkdir -p "$OUT/raw"
CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md"

if [ "${W5_SKIP_BUILD:-0}" != "1" ]; then
  {
    W5_COLL=docs                   mongosh --quiet --port "$PORT" --file "$HERE/w5_build.js"
    W5_COLL=docs_bar W5_MEDIUM=1   mongosh --quiet --port "$PORT" --file "$HERE/w5_build.js"
  } | tee "$OUT/raw/build.log"
fi

{
  # Control: no bar-setting class. Four permutations of {E x10, H x10}.
  W5_COLL=docs     W5_NPER=10 W5_NMEDQ=0 \
    W5_ORDERS=alternating,blocked_EH,blocked_HE,shuffled \
    mongosh --quiet --port "$PORT" --file "$HERE/w5_order.js"
  # The cliff: three permutations of {M x2, E x9, H x9} differing only in M's position.
  W5_COLL=docs_bar W5_NPER=9  W5_NMEDQ=2 \
    W5_ORDERS=M_first,M_last,M_middle,shuffled \
    mongosh --quiet --port "$PORT" --file "$HERE/w5_order.js"
} | tee "$OUT/raw/order.log"

grep -h '@@JSON@@' "$OUT"/raw/*.log | sed 's/@@JSON@@//' > "$OUT/w5.jsonl"
python3 "$HERE/w5_report.py" "$OUT/w5.jsonl" | tee "$OUT/report.txt"

# The standing requirement: CPU and peak memory, not latency alone. Also answers the
# scoping question -- is the order dependence present under the cost-based ranker?
python3 "$HERE/w5_resource_cost.py" | tee "$OUT/resources.txt"
echo "==> results in $OUT"

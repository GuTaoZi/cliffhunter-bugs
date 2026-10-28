#!/bin/sh
# SERVER-79039 -- reproduce a defect MongoDB closed Won't Do, using oracle O3.
#
#   claim     "a cycle of cache->evict->replan->cache for the same query shape AND SAME
#              PLAN depending on the parameters"; after the eviction the entry is
#              inactive, and a later cheap query re-promotes it at the LOW works value,
#              so "its like the higher work query never happened".
#   O3 test   one multiset {C x NC, E x NE} per epoch, four arrival orders. If the cycle
#             is real, alternating thrashes forever and blocked_EC does not -- on
#             byte-identical data, with byte-identical queries.
#   sweep     N_E is swept to show the thrash boundary is the one the mechanism predicts
#             (E's works > 10 x the cheap class's works), not a tuned constant.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
RUN="${1:-$(date +%Y-%m-%d)-jira-repro}"
OUT="$ROOT/experiments/existing-tools/$RUN"
REPS="${S2_REPS:-3}"
mkdir -p "$OUT/raw"
[ -f "$OUT/env.md" ] || CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md" 2>/dev/null || true

if [ "${S2_SKIP_BUILD:-0}" != "1" ]; then
  mongosh --quiet --port "$PORT" --file "$HERE/s79039_build.js" | tee "$OUT/raw/s79039_build.log"
fi

: > "$OUT/raw/s79039_order.log"
i=0
while [ "$i" -lt "$REPS" ]; do
  S2_REP="$i" mongosh --quiet --port "$PORT" --file "$HERE/s79039_order.js" \
    >> "$OUT/raw/s79039_order.log"
  i=$((i+1))
done

# The boundary. Predicted at N_E + 1 > 10 x 6 = 60, i.e. N_E >= 60.
: > "$OUT/raw/s79039_sweep.log"
for NE in 10 20 40 55 59 60 70 100 500 5000 50000; do
  S2_COLL=sweep S2_N_E="$NE" mongosh --quiet --port "$PORT" --file "$HERE/s79039_build.js" \
    > /dev/null
  S2_COLL=sweep S2_KIND=s79039_sweep S2_ORDERS=alternating S2_EPOCHS=3 \
    mongosh --quiet --port "$PORT" --file "$HERE/s79039_order.js" >> "$OUT/raw/s79039_sweep.log"
done

grep -h '@@JSON@@' "$OUT"/raw/s79039_*.log | sed 's/@@JSON@@//' > "$OUT/s79039.jsonl"
python3 "$HERE/s79039_report.py" "$OUT/s79039.jsonl" | tee "$OUT/s79039-report.txt"
python3 "$HERE/s79039_resource_cost.py" | tee "$OUT/s79039-resources.txt"
echo "==> results in $OUT"

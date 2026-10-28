#!/bin/sh
# SERVER-107471 -- reproduce a defect MongoDB closed Won't Do for want of a reproduction,
# using oracle O3 (order permutation).
#
#   premise   .skip() is not part of planCacheKey, so find(F,P).skip(S).limit(L) and
#             find(F,P).limit(L) share ONE plan cache entry.
#   defect    the multi-planner's trial-period result target ignores skip, so the skip
#             variant's winning plan and its decisionWorks are both distorted -- and
#             decisionWorks is the replan bar / 10. Whichever variant arrives first fixes
#             the plan AND the bar for the other.
#   control   arm 'noskip' deletes .skip(S) and changes nothing else.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
RUN="${1:-$(date +%Y-%m-%d)-jira-repro}"
OUT="$ROOT/experiments/existing-tools/$RUN"
REPS="${S1_REPS:-3}"
mkdir -p "$OUT/raw"
CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md" 2>/dev/null || true

if [ "${S1_SKIP_BUILD:-0}" != "1" ]; then
  mongosh --quiet --port "$PORT" --file "$HERE/s107471_build.js" | tee "$OUT/raw/s107471_build.log"
fi

: > "$OUT/raw/s107471_order.log"
i=0
while [ "$i" -lt "$REPS" ]; do
  # the defect arm and the no-skip control, same multiset, four arrival orders
  S1_REP="$i" S1_SKIP="${S1_SKIPN:-5000}" \
    mongosh --quiet --port "$PORT" --file "$HERE/s107471_order.js" >> "$OUT/raw/s107471_order.log"
  S1_REP="$i" S1_SKIP=0 \
    mongosh --quiet --port "$PORT" --file "$HERE/s107471_order.js" >> "$OUT/raw/s107471_order.log"
  i=$((i+1))
done

# How much tuning was involved: sweep the skip and show the threshold the mechanism predicts.
: > "$OUT/raw/s107471_sweep.log"
for S in 0 100 500 1000 1500 1800 2000 3000 5000 10000; do
  S1_KIND=s107471_sweep S1_SKIP="$S" S1_ORDERS=P_first \
    mongosh --quiet --port "$PORT" --file "$HERE/s107471_order.js" >> "$OUT/raw/s107471_sweep.log"
done

grep -h '@@JSON@@' "$OUT"/raw/s107471_*.log | sed 's/@@JSON@@//' > "$OUT/s107471.jsonl"
python3 "$HERE/s107471_report.py" "$OUT/s107471.jsonl" | tee "$OUT/s107471-report.txt"
python3 "$HERE/s107471_resource_cost.py" | tee "$OUT/s107471-resources.txt"
echo "==> results in $OUT"

#!/bin/sh
# W2 -- $lookup hash-join eligibility cliff at foreign collection = 10000 documents.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
RUN="${1:-$(date +%Y-%m-%d)-w2-hash-join}"
OUT="$ROOT/experiments/cliffs/$RUN"
mkdir -p "$OUT/raw"

echo "==> capturing environment"
CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md"

echo "==> building dataset"
mongosh --quiet --port "$PORT" --file "$HERE/w2_build.js" | tee "$OUT/raw/build.log"

echo "==> sweep"
mongosh --quiet --port "$PORT" --file "$HERE/w2_sweep.js" | tee "$OUT/raw/sweep.log"

grep -h '@@JSON@@' "$OUT"/raw/*.log | sed 's/@@JSON@@//' > "$OUT/w2.jsonl"
python3 "$H/analyze.py" "$OUT/w2.jsonl" --key foreign_docs | tee "$OUT/report.txt"
echo "==> results in $OUT"

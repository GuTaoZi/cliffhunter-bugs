#!/bin/sh
# W1 -- explode-for-sort cliff at |$in| = internalQueryMaxScansToExplode (200).
# Usage: W1_N=10000000 bugs/systems/mongodb/explode-for-sort/repro/run_w1.sh [run-name]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../../.." && pwd)   # this script is in bugs/systems/<system>/<bug>/repro/
H="$ROOT/tools/harness"                  # the shared harness: env.sh, analyze.py, lib.js, start_*
PORT="${CH_PORT:-15451}"
N="${W1_N:-2000000}"
RUN="${1:-$(date +%Y-%m-%d)-w1-explode-for-sort}"
OUT="$ROOT/experiments/cliffs/$RUN"
mkdir -p "$OUT/raw"

echo "==> capturing environment"
CH_PORT="$PORT" sh "$H/env.sh" > "$OUT/env.md"

echo "==> building dataset (N=$N)"
W1_N="$N" mongosh --quiet --port "$PORT" --file "$HERE/w1_build.js" | tee "$OUT/raw/build-n$N.log"

echo "==> noise floor"
mongosh --quiet --port "$PORT" --file "$HERE/noise_floor.js" | tee "$OUT/raw/noise-n$N.log"

echo "==> sweep"
mongosh --quiet --port "$PORT" --file "$HERE/w1_sweep.js" | tee "$OUT/raw/sweep-n$N.log"

grep -h '@@JSON@@' "$OUT"/raw/*-n"$N".log | sed 's/@@JSON@@//' > "$OUT/w1-n$N.jsonl"
python3 "$H/analyze.py" "$OUT/w1-n$N.jsonl" | tee "$OUT/report-n$N.txt"
echo "==> results in $OUT"

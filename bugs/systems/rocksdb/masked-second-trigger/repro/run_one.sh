#!/bin/sh
# One measured run of one arm.  run_one.sh SHA12 TAG [driver flags...]
# Writes results/TAG.json (driver summary + LOG decision counts), results/TAG.csv (time series),
# results/TAG.LOG (the RocksDB info log); the database is deleted afterwards.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -u
D=$SCRIPT_DIR
SHA=$1; TAG=$2; shift 2
mkdir -p "$D/results"
DB="$D/db-$TAG"
rm -rf "$DB"
"$D/wbm_driver-$SHA" --db="$DB" --csv="$D/results/$TAG.csv" "$@" > "$D/results/$TAG.out" 2> "$D/results/$TAG.err"
rc=$?
cp "$DB/LOG" "$D/results/$TAG.LOG" 2>/dev/null
python3 "$D/summarize_run.py" "$D/results/$TAG" "$SHA" "$TAG" "$rc" "$*"
rm -rf "$DB"

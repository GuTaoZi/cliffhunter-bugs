#!/bin/sh
# One measured run of one arm.   run_one.sh SHA12 TAG [driver flags...]
# Writes results/TAG.json (driver summary + LOG counts inside the measured window),
# results/TAG.LOG.gz (RocksDB info log); the database is deleted afterwards.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -u
D=$SCRIPT_DIR
SHA=$1; TAG=$2; shift 2
mkdir -p "$D/results"
DB="$D/db-$TAG"
rm -rf "$DB"
"$D/futile_driver-$SHA" --db="$DB" "$@" > "$D/results/$TAG.out" 2> "$D/results/$TAG.err"
rc=$?
python3 "$D/summarize_run.py" "$D/results/$TAG.out" "$DB/LOG" "$SHA" "$TAG" "$rc" "$*" > "$D/results/$TAG.json"
gzip -c "$DB/LOG" > "$D/results/$TAG.LOG.gz" 2>/dev/null
rm -rf "$DB"
cat "$D/results/$TAG.json"

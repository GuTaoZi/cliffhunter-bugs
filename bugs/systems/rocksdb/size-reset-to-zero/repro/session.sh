#!/bin/sh
# Rank 11 in one machine-lock acquisition: build both arms, fill the database, 5 alternated rounds, report.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
echo "$(date -Is) start"
python3 $D/run.py build
python3 $D/run.py fill
python3 $D/run.py measure 5
python3 $D/run.py report
echo "$(date -Is) end"

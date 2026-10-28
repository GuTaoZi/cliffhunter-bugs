#!/bin/sh
# Interleaved repetitions of the two arms for one configuration. Run under the machine lock:
#   flock .../locks/machine.lock series.sh NAME POLICY N MARGIN K REPS SETTLE
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
D=$SCRIPT_DIR
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build
NAME=$1; POLICY=$2; N=$3; MARGIN=$4; K=$5; REPS=$6; SETTLE=$7
OUT=$D/data/$NAME
mkdir -p "$OUT"
echo "series $NAME policy=$POLICY n=$N margin=$MARGIN k=$K reps=$REPS start=$(date -Is) load=$(cut -d' ' -f1-3 /proc/loadavg)"
r=1
while [ $r -le "$REPS" ]; do
  # alternate which arm goes first in each repetition
  if [ $((r % 2)) -eq 1 ]; then ARMS="parent:redis-2f41a3856845 fix:redis-75f9dec64455"; else ARMS="fix:redis-75f9dec64455 parent:redis-2f41a3856845"; fi
  for arm in $ARMS; do
    echo "# load=$(cut -d' ' -f1-3 /proc/loadavg) $(date -Is)"
    python3 $D/run.py --arm ${arm%%:*} --bin $B/${arm#*:}/src/src/redis-server --port 15430 \
      --n "$N" --margin "$MARGIN" --k "$K" --policy "$POLICY" --settle "$SETTLE" --rep $r --outdir "$OUT"
  done
  r=$((r + 1))
done
echo "end $(date -Is)"

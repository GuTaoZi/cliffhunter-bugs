#!/bin/sh
# Measured campaign: parent (4234cbad76c9) against fix (f2a4e5b491ed), interleaved, arm order
# alternating per repetition. Run the whole script under the machine lock:
#   flock ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock sh campaign.sh
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
D=$SCRIPT_DIR
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build
PARENT=$B/memcached-4234cbad76c9/src/memcached
FIX=$B/memcached-f2a4e5b491ed/src/memcached
OUT=$D/data/runs.jsonl
mkdir -p $D/data
REPS=${REPS:-5}
REPS_AGED=${REPS_AGED:-3}
date -Is
for rep in $(seq 1 $REPS); do
  if [ $((rep % 2)) -eq 1 ]; then ORDER="parent fix"; else ORDER="fix parent"; fi
  for cfg in refhang thousands-fresh thousands-aged; do
    if [ $cfg = thousands-aged ] && [ $rep -gt $REPS_AGED ]; then continue; fi
    for arm in $ORDER; do
      if [ $arm = parent ]; then BIN=$PARENT; else BIN=$FIX; fi
      python3 $D/stuck_tail.py --bin $BIN --arm $arm --config $cfg --rep $rep --port 15440 --out $OUT > /dev/null
      echo "$(date -Is) done $cfg $arm rep $rep"
    done
  done
done
date -Is

#!/bin/sh
# Measured campaign: REPS repetitions of both arms, interleaved (order alternates per rep:
# P F, F P, P F, ...), each run SECONDS long, same workload flags. Run the whole campaign under
# the machine lock:
#   flock ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock .../campaign.sh NAME REPS SECONDS [extra driver flags]
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -u
D=$SCRIPT_DIR
NAME=$1; REPS=$2; SECS=$3; shift 3
P=1560b2f5f014   # parent of the fix (buggy: else-if)
F=18eeb7b90e45   # fix (memory check evaluated independently)
FLAGS="--seconds=$SECS --cfs=20 --write_rate=33554432 --flush_rate=8388608 --db_write_buffer_size=67108864 --write_buffer_size=67108864 --max_write_buffer_number=4 --max_total_wal_size=33554432 --value_size=1000 --threads=1 --sample_ms=100 $*"
echo "campaign $NAME start $(date -Is) flags: $FLAGS"
i=1
while [ $i -le "$REPS" ]; do
  if [ $((i % 2)) -eq 1 ]; then ORDER="$P $F"; else ORDER="$F $P"; fi
  for A in $ORDER; do
    if [ "$A" = "$P" ]; then L=parent; else L=fix; fi
    echo "run $NAME-$L-$i $(date -Is)"
    "$D/run_one.sh" "$A" "$NAME-$L-$i" $FLAGS
    sleep 3
  done
  i=$((i + 1))
done
echo "campaign $NAME end $(date -Is)"

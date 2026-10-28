#!/bin/sh
# All measured runs, meant to be run as ONE job under the machine lock:
#   flock ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock sh run_all.sh [VARIANT...]
# Arms: P = 8b886a4e3488 (parent of the fix), F = a1b4f289beec (the fix), both built by tools/reproduce/build.sh (-O2).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
D=$SCRIPT_DIR
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build
ARMS="--arm P=$B/postgres-8b886a4e3488/install:15420 --arm F=$B/postgres-a1b4f289beec/install:15421"
cd "$D"
VARIANTS=${*:-A B C D E}
for V in $VARIANTS; do
  case $V in
    # A: duplicate key -57267 (hashint4 = 698: batch bits zero, so the group stays in batch 0 while the
    #    hashed side is built); distinct keys first, the duplicate group last.
    A) P="--ds a --n-distinct 200000 --n-dup 100000 --n-outer 600000 --order dups-last --dup-key -57267 --reps 5" ;;
    # B: the same with an ordinary duplicate key (0); the group leaves batch 0 early and explodes when its batch is loaded.
    B) P="--ds b --n-distinct 200000 --n-dup 100000 --n-outer 600000 --order dups-last --dup-key 0 --reps 5" ;;
    # C: the miner's hint taken literally: one key repeated 10M times, nothing else on the hashed side.
    C) P="--ds c --n-distinct 0 --n-dup 10000000 --n-outer 12000000 --order dups-last --dup-key 0 --reps 3" ;;
    # D: as A, but the duplicate group interleaved at random with the distinct keys.
    D) P="--ds d --n-distinct 200000 --n-dup 100000 --n-outer 600000 --order shuffled --dup-key -57267 --reps 5" ;;
    # E: as A, every table twice as large (does the parent's cost scale with the data while the fix's stays put?).
    E) P="--ds e --n-distinct 400000 --n-dup 200000 --n-outer 1200000 --order dups-last --dup-key -57267 --reps 3" ;;
    *) echo "unknown variant $V"; exit 2 ;;
  esac
  echo "=== variant $V $(date -Is)"
  python3 workload.py setup $ARMS $P
  python3 workload.py run $ARMS $P --warmup --tag "$V"
  python3 workload.py stop $ARMS $P
  echo "=== variant $V done $(date -Is)"
done

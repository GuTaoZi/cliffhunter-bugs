#!/bin/sh
# Rank 8, second setup (run as: flock LOCK sh rank8b.sh): preserve_internal_time_seconds=100 (RocksDB then records
# its seqno-to-time mapping about every second), writes spread over 20 s, then a 30 s idle window while the data is
# still inside the preserve window. A smoke pair first; then 5 alternated repetitions if the parent loops.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
sh $D/link8.sh
mkdir -p $D/results
run() { rm -rf $D/db; $D/bottom_loop-$1 --db=$D/db --preserve_seconds=100 --spread_s=20 --keys=100000 --value_size=1000 --seconds=30 > $D/results/$2.json; echo "$(date -Is) $2 $(cut -c1-200 $D/results/$2.json)"; }
run 6dbb6f30e604 r8b-smoke-parent
run f7b791b213b2 r8b-smoke-fix
if grep -q '"compactions_in_window": [0-9][0-9]' $D/results/r8b-smoke-parent.json; then
  for r in 1 2 3 4 5; do
    if [ $((r % 2)) -eq 1 ]; then O="6dbb6f30e604 f7b791b213b2"; else O="f7b791b213b2 6dbb6f30e604"; fi
    for S in $O; do run $S r8b-$S-r$r; done
  done
fi
rm -rf $D/db

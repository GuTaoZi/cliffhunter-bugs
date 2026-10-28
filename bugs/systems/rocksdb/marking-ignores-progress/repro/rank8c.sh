#!/bin/sh
# Rank 8, third setup (run as: flock LOCK sh rank8c.sh): as rank8b.sh, with the file moved to the last level (6),
# as the fix's test does (MoveFilesToLevel(kNumLevels - 1)). A smoke pair; 5 alternated repetitions if the parent loops.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
sh $D/link8.sh
mkdir -p $D/results
run() { rm -rf $D/db; $D/bottom_loop-$1 --db=$D/db --preserve_seconds=100 --spread_s=20 --target_level=6 --keys=100000 --value_size=1000 --seconds=30 > $D/results/$2.json; echo "$(date -Is) $2 $(cut -c1-200 $D/results/$2.json)"; }
run 6dbb6f30e604 r8c-smoke-parent
run f7b791b213b2 r8c-smoke-fix
if grep -q '"compactions_in_window": [0-9][0-9]' $D/results/r8c-smoke-parent.json; then
  for r in 1 2 3 4 5; do
    if [ $((r % 2)) -eq 1 ]; then O="6dbb6f30e604 f7b791b213b2"; else O="f7b791b213b2 6dbb6f30e604"; fi
    for S in $O; do run $S r8c-$S-r$r; done
  done
fi
rm -rf $D/db

#!/bin/sh
# Measured campaign for ranks 9 and 8 (run as: flock LOCK sh campaign.sh): 5 repetitions per arm, arm order
# alternated, a 30 s idle window after the setup; one JSON line per run in results/.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
mkdir -p $D/results
echo "$(date -Is) campaign start"
for r in 1 2 3 4 5; do
  if [ $((r % 2)) -eq 1 ]; then O9="00d697bdc532 eca47fb6960e"; O8="6dbb6f30e604 f7b791b213b2";
  else O9="eca47fb6960e 00d697bdc532"; O8="f7b791b213b2 6dbb6f30e604"; fi
  for S in $O9; do
    rm -rf $D/db; $D/bottom_loop-$S --db=$D/db --ingest_behind=1 --keys=100000 --value_size=1000 --seconds=30 > $D/results/r9-$S-r$r.json
    echo "$(date -Is) rank9 $S r$r $(cat $D/results/r9-$S-r$r.json | cut -c1-160)"
  done
  for S in $O8; do
    rm -rf $D/db; $D/bottom_loop-$S --db=$D/db --preserve_seconds=10000 --keys=100000 --value_size=1000 --seconds=30 > $D/results/r8-$S-r$r.json
    echo "$(date -Is) rank8 $S r$r $(cat $D/results/r8-$S-r$r.json | cut -c1-160)"
  done
done
rm -rf $D/db
echo "$(date -Is) campaign end"

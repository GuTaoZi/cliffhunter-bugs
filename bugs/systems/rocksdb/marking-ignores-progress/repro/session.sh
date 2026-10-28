#!/bin/sh
# Ranks 8 and 9 in one machine-lock acquisition: build the four arms, link the driver, a smoke run of each arm.
#   rank 9 (allow_ingest_behind): parent 00d697bdc532, fix eca47fb6960e
#   rank 8 (preserve_internal_time_seconds): parent 6dbb6f30e604, fix f7b791b213b2
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../../../.." && pwd)
D=$SCRIPT_DIR
R=$REPO_ROOT
echo "$(date -Is) start"
for S in 00d697bdc532 eca47fb6960e 6dbb6f30e604 f7b791b213b2; do
  /usr/bin/env time -f "build $S: wall %e s, CPU %U+%S s, peak %M KB" sh $R/tools/reproduce/build.sh rocksdb $S 2>&1 | tail -2
done
for S in 00d697bdc532 eca47fb6960e; do sh $D/link.sh $S > $D/link-$S.out 2>&1; echo "link $S rc=$?"; done
for S in 6dbb6f30e604 f7b791b213b2; do sh $D/link.sh $S -DBOTTOM_LOOP_PRESERVE > $D/link-$S.out 2>&1; echo "link $S rc=$?"; done
mkdir -p $D/results
for S in 00d697bdc532 eca47fb6960e; do
  rm -rf $D/db; $D/bottom_loop-$S --db=$D/db --ingest_behind=1 --keys=100000 --value_size=1000 --seconds=20 | tee $D/results/smoke-r9-$S.json
done
for S in 6dbb6f30e604 f7b791b213b2; do
  rm -rf $D/db; $D/bottom_loop-$S --db=$D/db --preserve_seconds=10000 --keys=100000 --value_size=1000 --seconds=20 | tee $D/results/smoke-r8-$S.json
done
rm -rf $D/db
echo "$(date -Is) end"

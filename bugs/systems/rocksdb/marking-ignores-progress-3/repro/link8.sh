#!/bin/sh
# Link the driver against rank 8's two 2026 arms (preserve option and the unique_ptr DB::Open).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
for S in 6dbb6f30e604 f7b791b213b2; do
  sh $D/link.sh $S "-DBOTTOM_LOOP_PRESERVE -DBOTTOM_LOOP_UNIQUE" > $D/link-$S.out 2>&1
  echo "link $S rc=$?"
  grep -m4 'error' $D/link-$S.out | cut -c1-240
done

#!/bin/sh
# Link the driver against both arms, then a 6 s smoke run per (config, arm). Run under the machine lock.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
for A in b7e1c5213f00 416943bf28b4; do
  sh $D/link_driver.sh $A > $D/link-$A.out 2>&1; echo "link $A rc=$?"; tail -1 $D/link-$A.out
done
for CFG in 0 100; do
  for A in b7e1c5213f00 416943bf28b4; do
    if [ $A = b7e1c5213f00 ]; then ARM=parent; else ARM=fix; fi
    $D/run_one.sh $A smoke2-k$CFG-$ARM-r0 --seconds=6 --write_rate=20000 --value_size=1024 \
      --write_buffer_size=4194304 --snap_threads=2 --snap_rate=20000 --cold_cfs=$CFG | cut -c1-600
  done
done

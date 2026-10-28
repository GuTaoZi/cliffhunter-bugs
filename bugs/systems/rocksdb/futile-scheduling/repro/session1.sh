#!/bin/sh
# Everything in one machine-lock acquisition (run as: flock LOCK sh session1.sh), kept under ~19 min:
#   builds of both arms, driver links, a 6 s smoke run per (config, arm), then a short wait (max 4 min)
#   for a decision file (params.go: extra driver flags, or params.stop), then campaign rounds while
#   the hold is under 15 minutes old at the start of a round.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
T0=$(date +%s)
echo "$(date -Is) session1: lock acquired"
sh $D/build_arm.sh b7e1c5213f00 > $D/build-parent.out 2>&1; echo "$(date -Is) parent build rc=$?"
sh $D/build_arm.sh 416943bf28b4 > $D/build-fix.out 2>&1; echo "$(date -Is) fix build rc=$?"
sh $D/link_driver.sh b7e1c5213f00 > $D/link-parent.out 2>&1; echo "$(date -Is) parent link rc=$?"
sh $D/link_driver.sh 416943bf28b4 > $D/link-fix.out 2>&1; echo "$(date -Is) fix link rc=$?"
for CFG in 0 100; do
  for A in b7e1c5213f00 416943bf28b4; do
    if [ $A = b7e1c5213f00 ]; then ARM=parent; else ARM=fix; fi
    $D/run_one.sh $A smoke-k$CFG-$ARM-r0 --seconds=6 --write_rate=20000 --value_size=1024 \
      --write_buffer_size=4194304 --snap_threads=2 --snap_rate=20000 --cold_cfs=$CFG
  done
done
echo "$(date -Is) smoke done; waiting for params.go / params.stop"
rm -f $D/params.go $D/params.stop
i=0
while [ $i -lt 240 ] && [ ! -f $D/params.go ] && [ ! -f $D/params.stop ]; do sleep 1; i=$((i + 1)); done
[ -f $D/params.stop ] && { echo "$(date -Is) stop requested"; exit 0; }
EXTRA=$(cat $D/params.go 2>/dev/null)
echo "$(date -Is) campaign extra flags: [$EXTRA]"
r=1
while [ $(( $(date +%s) - T0 )) -lt 900 ] && [ $r -le 5 ]; do
  sh $D/campaign.sh $r main $EXTRA
  r=$((r + 1))
done
echo "$(date -Is) session1: released after $(( $(date +%s) - T0 )) s, rounds done: $((r - 1))"

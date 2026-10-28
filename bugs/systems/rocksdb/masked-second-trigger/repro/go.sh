#!/bin/sh
# Everything heavy, in one machine-lock acquisition:
#   flock ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock .../go.sh
# 1. relink the driver against each arm's release objects;
# 2. main campaign: 3 interleaved repetitions per arm, 90 s each;
# 3. one long run per arm (180 s) to show whether the growth levels off.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -u
D=$SCRIPT_DIR
echo "go start $(date -Is)"
"$D/link_driver.sh" 1560b2f5f014 || exit 1
"$D/link_driver.sh" 18eeb7b90e45 || exit 1
"$D/run_one.sh" 18eeb7b90e45 smoke2-fix --seconds=4
grep -q peak_active_memtables_mb "$D/results/smoke2-fix.json" || { echo "smoke2 failed"; exit 1; }
grep -q csv_error "$D/results/smoke2-fix.json" && { echo "smoke2 csv failed"; exit 1; }
"$D/campaign.sh" main 3 90
"$D/campaign.sh" long 1 180
echo "go end $(date -Is)"

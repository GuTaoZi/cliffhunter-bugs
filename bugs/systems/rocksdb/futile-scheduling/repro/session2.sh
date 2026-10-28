#!/bin/sh
# The measured campaign, 5 rounds, under one machine-lock acquisition (run as: flock LOCK sh session2.sh).
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
echo "$(date -Is) session2 start"
for r in 1 2 3 4 5; do sh $D/campaign.sh $r main2; done
echo "$(date -Is) session2 end"

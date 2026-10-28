#!/bin/sh
# Run rounds FIRST..LAST of the campaign, one machine-lock acquisition per round (each ~2 min).
#   go.sh FIRST LAST [PREFIX] [EXTRA_FLAGS...]
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
L=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock
A=$1; B=$2; shift 2
r=$A
while [ $r -le $B ]; do
  flock $L sh $D/campaign.sh $r "$@"
  r=$((r + 1))
done
echo "$(date -Is) done"

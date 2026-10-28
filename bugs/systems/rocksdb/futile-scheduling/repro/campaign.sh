#!/bin/sh
# One round of the measured campaign: every (config, arm) once, order alternated by round parity.
#   campaign.sh ROUND [PREFIX] [EXTRA_FLAGS...]      (run under the machine lock by go.sh)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -u
D=$SCRIPT_DIR
P=b7e1c5213f00   # parent of the fix
F=416943bf28b4   # fix
R=$1; PFX=${2:-main}; shift; [ $# -gt 0 ] && shift
COMMON="--seconds=20 --write_rate=20000 --value_size=1024 --write_buffer_size=4194304 --snap_threads=2 --snap_rate=20000 $*"
if [ $((R % 2)) -eq 1 ]; then ORDER="$P $F"; else ORDER="$F $P"; fi
# k1000 added on 2026-10-27 after the smoke runs: 100 cold column families gave 355 futile jobs in 6 s but little CPU.
for CFG in k0 k100 k1000; do
  case $CFG in k0) X="--cold_cfs=0";; k100) X="--cold_cfs=100";; k1000) X="--cold_cfs=1000";; esac
  for A in $ORDER; do
    if [ $A = $P ]; then ARM=parent; else ARM=fix; fi
    echo "$(date -Is) round=$R cfg=$CFG arm=$ARM"
    "$D/run_one.sh" $A "$PFX-$CFG-$ARM-r$R" $COMMON $X
  done
done

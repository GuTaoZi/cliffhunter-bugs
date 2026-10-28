#!/bin/sh
# Build both arms, one lock acquisition per build.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
D=$SCRIPT_DIR
L=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock
flock $L $D/build_arm.sh b7e1c5213f00 > $D/build-parent.out 2>&1; echo parent rc=$?
flock $L $D/build_arm.sh 416943bf28b4 > $D/build-fix.out 2>&1; echo fix rc=$?

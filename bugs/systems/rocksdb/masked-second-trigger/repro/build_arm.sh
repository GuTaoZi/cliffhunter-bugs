#!/bin/sh
# Build one arm with the project's build script (release, flags recorded in flags.txt).
#   build_arm.sh COMMIT   -> ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/rocksdb-<sha12>/
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$(dirname "$0")/../../../../.." && pwd)  # this script is in bugs/systems/<system>/<bug>/repro/
set -eu
D=$SCRIPT_DIR
cd $REPO_ROOT
date -Is
sh tools/reproduce/build.sh rocksdb "$1"
rc=$?
date -Is
exit $rc

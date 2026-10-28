#!/bin/sh
# Build one arm with the project's build script (release, flags recorded in flags.txt).
#   build_arm.sh COMMIT   -> ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/rocksdb-<sha12>/
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../../../.." && pwd)
set -eu
cd $REPO_ROOT
date -Is
sh tools/reproduce/build.sh rocksdb "$1"
rc=$?
date -Is
exit $rc

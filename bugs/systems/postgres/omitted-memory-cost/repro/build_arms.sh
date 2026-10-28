#!/bin/sh
# Build the two arms (fix's parent, fix) with the project's release build script, one at a time, under the machine lock.
REPO_ROOT=$(cd "$(dirname "$0")/../../../../.." && pwd)  # this script is in bugs/systems/<system>/<bug>/repro/
set -eu
W=$REPO_ROOT
LOCK=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/locks/machine.lock
PARENT=8b886a4e34886bf2d1dd4f5e7d95f4ddadc3afa8
FIX=a1b4f289beec19534e5e34e1a962c5828b306ce2
cd "$W"
flock "$LOCK" sh tools/reproduce/build.sh postgres "$PARENT"
flock "$LOCK" sh tools/reproduce/build.sh postgres "$FIX"

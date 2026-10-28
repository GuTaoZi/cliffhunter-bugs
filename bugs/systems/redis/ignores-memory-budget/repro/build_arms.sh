#!/bin/sh
# Build the two arms (fix's parent, fix) with the project's release build script.
REPO_ROOT=$(cd "$(dirname "$0")/../../../../.." && pwd)  # this script is in bugs/systems/<system>/<bug>/repro/
T=$REPO_ROOT/tools/reproduce/build.sh
for c in 2f41a3856845 75f9dec64455; do
  sh "$T" redis "$c"; echo "exit $? for $c"
done

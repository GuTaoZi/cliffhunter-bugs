#!/bin/sh
# Everything in one machine-lock acquisition (run as: flock LOCK sh session.sh), about 12 min:
#   1. release builds of both arms with tools/reproduce/build.sh. memcached 1.4.20's autogen.sh only
#      looks for versioned automake binaries (automake-1.14 .. automake-1.7) and has no fallback to a
#      plain `automake`, so AUTOMAKE=automake is passed (it only locates the tool, no code change);
#   2. a version check of both binaries;
#   3. the measured campaign (campaign.sh), then the tables (tables.py -> results.md).
# Any failure stops the session, so the lock is not held for nothing.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$(dirname "$0")/../../../../.." && pwd)  # this script is in bugs/systems/<system>/<bug>/repro/
set -eu
D=$SCRIPT_DIR
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build
T=$REPO_ROOT/tools/reproduce
mkdir -p $D/logs
echo "$(date -Is) session: lock acquired"
for c in 4234cbad76c9 f2a4e5b491ed; do
  AUTOMAKE=automake sh $T/build.sh memcached $c > $D/logs/build-$c.out 2>&1 || {
    echo "$(date -Is) build $c failed"; tail -20 $B/memcached-$c/build.log; exit 1; }
  echo "$(date -Is) build $c ok: $(tr '\n' ' ' < $B/memcached-$c/flags.txt)"
  $B/memcached-$c/src/memcached -h | head -1
done
REPS=5 REPS_AGED=3 sh $D/campaign.sh
python3 $D/tables.py > /dev/null
echo "$(date -Is) session: done"

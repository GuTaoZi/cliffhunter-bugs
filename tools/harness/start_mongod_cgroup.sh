#!/bin/sh
# Start mongod inside a systemd USER service so CPU and peak memory can be attributed to
# the server alone (the mongosh client's own cost is excluded). Same dbpath, port and
# pinned cache as start_mongod.sh -- this is that script plus resource accounting, which
# the standing requirement in docs/oracle-o1-refinement.md makes mandatory for every run.
#
# No root needed: the user manager delegates the cpu and memory controllers, so
# cpu.stat/memory.peak appear under the unit's cgroup automatically on cgroup v2.
set -eu
PORT="${CH_PORT:-15451}"
UNIT="${CH_UNIT:-mongod-ch}"
CH_DATA_ROOT="${CH_DATA_ROOT:-${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}}"
DBPATH="${CH_DBPATH:-$CH_DATA_ROOT/mongo/data/w1}"
LOGPATH="${CH_LOGPATH:-$CH_DATA_ROOT/mongo/log/w1.log}"
CACHE_GB="${CH_CACHE_GB:-8}"
# CH_TEST_COMMANDS=1 enables MongoDB's failpoint machinery. Needed by tools/harness/h2_bfa.js,
# which emulates branch-flip analysis (QueryZen/BFA) using the branch-flip points the server
# already exposes -- knobs and failpoints. Off by default: enabling test commands changes
# server behaviour in other ways, so it must never be on for a performance run that is
# being compared against one where it was off.
TESTCMD=""
[ "${CH_TEST_COMMANDS:-0}" = "1" ] && TESTCMD="--setParameter enableTestCommands=1"
mkdir -p "$DBPATH" "$(dirname "$LOGPATH")"

# Shut down any mongod already holding the dbpath, however it was started. A running
# server on a foreign cgroup is the failure this script exists to prevent, so an
# already-up mongod is NOT treated as success.
if mongosh --quiet --port "$PORT" --eval 'db.getSiblingDB("admin").shutdownServer({force:true})' \
     >/dev/null 2>&1; then
  echo "shut down existing mongod on $PORT"
fi
systemctl --user stop "$UNIT.service" 2>/dev/null || true
systemctl --user reset-failed "$UNIT.service" 2>/dev/null || true
# The socket lingers briefly after shutdown; wait for the port to actually free up.
i=0; while mongosh --quiet --port "$PORT" --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -gt 30 ] && { echo "port $PORT still busy" >&2; exit 1; }
  sleep 1
done

# --fork is deliberately omitted: systemd must own the main process for the cgroup to
# track it, so mongod stays in the foreground and the unit is Type=simple.
systemd-run --user --unit="$UNIT" --collect \
  --property=MemoryAccounting=yes --property=CPUAccounting=yes \
  -- mongod --dbpath "$DBPATH" --port "$PORT" \
            --wiredTigerCacheSizeGB "$CACHE_GB" --logpath "$LOGPATH" --bind_ip 127.0.0.1 \
            $TESTCMD \
  >/dev/null

i=0; until mongosh --quiet --port "$PORT" --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -gt 60 ] && { echo "mongod did not come up; see $LOGPATH" >&2; exit 1; }
  sleep 1
done
CG=$(systemctl --user show -p ControlGroup --value "$UNIT.service")
echo "mongod on 127.0.0.1:$PORT (cache ${CACHE_GB}GB, dbpath $DBPATH)"
echo "cgroup: /sys/fs/cgroup$CG"

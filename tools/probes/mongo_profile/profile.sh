#!/bin/sh
# Profile SERVER-79039 and SERVER-107471 on a mongod: a perf call graph of the server during the slow and the fast
# arrival order of the same queries, with wall time, the server's CPU (its cgroup's cpu.stat) and its peak RSS.
#
#   MONGOD=/path/to/mongod [MONGOD_LIBS=dir] flock $CLIFF_DATA/locks/machine.lock sh tools/probes/mongo_profile/profile.sh [REPS]
#   python3 tools/probes/mongo_profile/counters.py "$OUT"; python3 tools/probes/mongo_profile/shares.py "$OUT" > "$OUT/shares.md"
#
# mongod runs in a systemd user unit (its own cgroup) on port 15451 with a fresh dbpath under the data root. Each arm
# runs one order alone, with more epochs than the recorded runs so that a profile holds enough samples:
# SERVER-79039 alternating (slow) vs blocked_EC (fast); SERVER-107471 P_first (the skip query caches its plan first:
# slow) vs R_first (fast), skip 5000. Arms alternate per repetition. perf comes from nix-shell -p perf unless PERF
# is set; frame-pointer call graphs need a mongod built with -fno-omit-frame-pointer (MongoDB's default).
# Writes $OUT: buildinfo.json, <bug>-<arm>-r<rep>.{log,perf.data,self.txt,children.txt,folded}, runs.jsonl.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$HERE/../../.." && pwd)
D=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}
MONGOD=${MONGOD:-mongod}
MONGOD_LIBS=${MONGOD_LIBS:-}
PORT=${CH_PORT:-15451}
UNIT=${CH_UNIT:-mongod-prof}
REPS=${1:-2}
E79=${E79:-120}
E107=${E107:-150}
RUN=$D/mongo/run/profiles
O=${OUT:-$D/repro/mongodb-profiles/out}
PERF=${PERF:-$(nix-shell -p perf --run 'command -v perf')}
rm -rf "$RUN"; mkdir -p "$RUN/db" "$O"
: > "$O/runs.jsonl"

systemctl --user stop "$UNIT.service" 2>/dev/null || true
systemctl --user reset-failed "$UNIT.service" 2>/dev/null || true
systemd-run --user --unit="$UNIT" --collect --property=MemoryAccounting=yes --property=CPUAccounting=yes \
  ${MONGOD_LIBS:+--setenv=LD_LIBRARY_PATH="$MONGOD_LIBS"} -- "$(command -v "$MONGOD")" --dbpath "$RUN/db" \
  --port "$PORT" --bind_ip 127.0.0.1 --wiredTigerCacheSizeGB 8 --logpath "$RUN/mongod.log" >/dev/null
i=0; until mongosh --quiet --port "$PORT" --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; do
  i=$((i+1)); [ "$i" -gt 120 ] && { echo "mongod did not come up" >&2; exit 1; }; sleep 0.5
done
PID=$(systemctl --user show -p MainPID --value "$UNIT.service")
CG=/sys/fs/cgroup$(systemctl --user show -p ControlGroup --value "$UNIT.service")
mongosh --quiet --port "$PORT" --eval 'JSON.stringify(db.adminCommand({buildInfo:1}))' > "$O/buildinfo.json"
echo "mongod pid $PID, cgroup $CG"

D79=$R/bugs/systems/mongodb/SERVER-79039/repro
D107=$R/bugs/systems/mongodb/SERVER-107471/repro
cd "$D79" && mongosh --quiet --port "$PORT" --file s79039_build.js > "$O/s79039_build.log"
cd "$D107" && mongosh --quiet --port "$PORT" --file s107471_build.js > "$O/s107471_build.log"

one() {  # one BUG ARM REP DIR SCRIPT ENV...
  bug=$1 arm=$2 rep=$3 dir=$4 script=$5; shift 5
  tag=$bug-$arm-r$rep
  cd "$dir"
  cpu0=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat")
  echo 5 > "/proc/$PID/clear_refs"
  "$PERF" record -q -F 499 -g -p "$PID" -o "$O/$tag.perf.data" 2>/dev/null &
  pp=$!
  sleep 1
  t0=$(date +%s.%N)
  env "$@" mongosh --quiet --port "$PORT" --file "$script" > "$O/$tag.log"
  t1=$(date +%s.%N)
  kill -INT "$pp"; wait "$pp" || true
  cpu1=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat")
  hwm=$(awk '/^VmHWM/{print $2}' "/proc/$PID/status")
  python3 -c 'import json, sys; b, a, r, t0, t1, c0, c1, h = sys.argv[1:]; print(json.dumps({"bug": b, "arm": a, "rep": int(r),
    "wall_s": round(float(t1) - float(t0), 2), "server_cpu_s": round((int(c1) - int(c0)) / 1e6, 2),
    "server_peak_rss_mb": round(int(h) / 1024)}))' "$bug" "$arm" "$rep" "$t0" "$t1" "$cpu0" "$cpu1" "$hwm" >> "$O/runs.jsonl"
  tail -1 "$O/runs.jsonl"
  "$PERF" report -i "$O/$tag.perf.data" --no-children --sort sym --stdio --percent-limit 0.5 2>/dev/null > "$O/$tag.self.txt"
  "$PERF" report -i "$O/$tag.perf.data" --children --sort sym --stdio --percent-limit 1 -g none 2>/dev/null > "$O/$tag.children.txt"
  "$PERF" script -i "$O/$tag.perf.data" -F comm,tid,ip,sym 2>/dev/null | python3 "$HERE/fold.py" > "$O/$tag.folded"
}

rep=1
while [ "$rep" -le "$REPS" ]; do
  if [ $((rep % 2)) = 1 ]; then o79="alternating blocked_EC"; o107="P_first R_first"; else o79="blocked_EC alternating"; o107="R_first P_first"; fi
  for o in $o79; do one s79039 "$o" "$rep" "$D79" s79039_order.js S2_ORDERS="$o" S2_EPOCHS="$E79" S2_REP="$rep"; done
  for o in $o107; do one s107471 "$o" "$rep" "$D107" s107471_order.js S1_ORDERS="$o" S1_EPOCHS="$E107" S1_SKIP=5000 S1_REP="$rep"; done
  rep=$((rep + 1))
done

mongosh --quiet --port "$PORT" --eval 'db.adminCommand({shutdown:1, force:true})' >/dev/null 2>&1 || true
systemctl --user stop "$UNIT.service" 2>/dev/null || true
rm -rf "$RUN/db"
echo "done $(date -Is)"

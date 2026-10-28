#!/bin/sh
# Capture the host facts a performance claim depends on. Emitted into results/<run>/env.md.
set -eu
PORT="${CH_PORT:-15451}"
echo "# Environment"
echo
echo '```'
echo "date          : $(date -Is)"
echo "host          : $(hostname)"
echo "kernel        : $(uname -srm)"
echo "cpu           : $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
echo "cores         : $(nproc)"
echo "mem_total     : $(awk '/MemTotal/{printf "%.0f GB", $2/1048576}' /proc/meminfo)"
echo "governor      : $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'n/a')"
echo "thp_enabled   : $(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo 'n/a')"
echo "thp_defrag    : $(cat /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || echo 'n/a')"
echo "mongod        : $(mongod --version 2>/dev/null | head -1)"
echo "mongosh       : $(mongosh --version 2>/dev/null | head -1)"
echo "mongod_argv   : $(ps -o args= -C mongod 2>/dev/null | head -1)"
echo '```'
echo
echo "## Knob values read from the running server"
echo
echo '```'
mongosh --quiet --port "$PORT" --eval '
const knobs = ["internalQueryMaxScansToExplode",
               "internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin",
               "internalQueryCollectionMaxDataSizeBytesToChooseHashJoin",
               "internalQueryCollectionMaxStorageSizeBytesToChooseHashJoin",
               "internalQueryDisableLookupExecutionUsingHashJoin",
               "internalDocumentSourceLookupCacheSizeBytes",
               "internalQueryFrameworkControl",
               "internalQueryPlanEvaluationMaxResults",
               "internalQueryPlanRanker"];
for (const k of knobs) {
  try { const r = db.adminCommand({getParameter: 1, [k]: 1});
        let v = r[k];
        if (v && typeof v === "object" && "low" in v) v = v.low;
        print(k.padEnd(56) + " = " + JSON.stringify(v)); }
  catch (e) { print(k.padEnd(56) + " = <unavailable: " + e.codeName + ">"); }
}
print("server version".padEnd(56) + " = " + db.version());'
echo '```'

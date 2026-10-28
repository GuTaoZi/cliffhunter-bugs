#!/usr/bin/env python3
"""Measure what each $lookup plan costs in CPU and memory, not just wall-clock.

Latency alone hides the real trade the heuristic is making. Hash join spends MEMORY
(a hash table over the foreign collection) to save CPU; nested loop spends CPU to save
memory. The eligibility cap is nominally protecting memory -- so the honest question is
how much memory it actually saves, and how much CPU it spends to do so.

mongod runs inside a systemd user cgroup so CPU and peak memory can be attributed to the
server alone, with the mongosh client's own cost excluded.
"""
import os
import shutil
import subprocess
import sys

UNIT = os.environ.get("CH_UNIT", "mongod-capped")  # the systemd user unit mongod runs in (start_mongod_cgroup.sh)
CG = (f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/"
      f"user@{os.getuid()}.service/app.slice/{UNIT}.service")
MONGOSH = os.environ.get("MONGOSH") or shutil.which("mongosh") or "mongosh"
PORT = os.environ.get("CH_PORT", "15451")
REPS = int(os.environ.get("RC_REPS", "5"))


def sh(js):
    subprocess.run([MONGOSH, "--quiet", "--port", PORT, "--eval", js],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def read(path, key=None):
    with open(path) as fh:
        txt = fh.read()
    if key is None:
        return int(txt.strip())
    for line in txt.splitlines():
        if line.startswith(key):
            return int(line.split()[1])
    raise KeyError(key)


def pipeline(foreign):
    return (f"db.getSiblingDB('w2').local.aggregate(["
            f"{{$lookup:{{from:'foreign_{foreign}',localField:'f',foreignField:'g',as:'out'}}}},"
            f"{{$group:{{_id:null,t:{{$sum:{{$size:'$out'}}}}}}}}]).toArray();")


def phase(label, foreign, knob):
    sh(f"db.adminCommand({{setParameter:1, internalQueryFrameworkControl:'trySbeEngine'}});"
       f"db.adminCommand({{setParameter:1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin:{knob}}});"
       + pipeline(foreign))                      # warm up, and settle the plan

    try:                                          # reset the peak watermark if supported
        with open(f"{CG}/memory.peak", "w") as fh:
            fh.write("0")
    except OSError:
        pass

    cpu0 = read(f"{CG}/cpu.stat", "usage_usec")
    for _ in range(REPS):
        sh(pipeline(foreign))
    cpu1 = read(f"{CG}/cpu.stat", "usage_usec")

    try:
        peak = read(f"{CG}/memory.peak")
    except OSError:
        peak = read(f"{CG}/memory.current")

    return {"label": label, "cpu_ms": (cpu1 - cpu0) / REPS / 1000.0,
            "peak_mb": peak / 1048576.0}


def main():
    rows = [phase("foreign=10000  HASH (allowed)", 10000, 10000),
            phase("foreign=10001  NESTED LOOP", 10001, 10000),
            phase("foreign=10001  HASH (cap raised)", 10001, 20000)]
    sh("db.adminCommand({setParameter:1, internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin:10000});"
       "db.adminCommand({setParameter:1, internalQueryFrameworkControl:'trySbeRestricted'})")

    print(f"{'plan':<34} {'CPU ms/query':>14} {'mongod peak MB':>16}")
    print("-" * 66)
    for r in rows:
        print(f"{r['label']:<34} {r['cpu_ms']:>14.1f} {r['peak_mb']:>16.1f}")
    hash_, nl = rows[0], rows[1]
    print()
    print(f"nested loop costs {nl['cpu_ms']/max(hash_['cpu_ms'],1e-9):,.0f}x the CPU of hash join")
    print(f"peak memory difference: {nl['peak_mb'] - hash_['peak_mb']:+.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

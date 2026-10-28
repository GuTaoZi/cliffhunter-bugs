#!/usr/bin/env python3
"""CPU and peak memory for the SERVER-79039 reproduction, per the standing requirement.

mongod runs inside a systemd user service (tools/harness/start_mongod_cgroup.sh) so CPU and
memory are attributed to the server alone and exclude the mongosh client.

KNOWN KERNEL BUG, worked around here: on kernel 6.x `echo reset > memory.peak` is accepted
and silently ignored, so memory.peak reports a stale global watermark. This samples
memory.current at 10 ms instead, which is what the newer harnesses do.

Quiet mode (S2_QUIET=1) drops the profiler and the per-query $planCacheStats polling:
with polling on, client wall time is dominated by two extra aggregations per query, so a
CPU number from a traced run means nothing. Cost is only ever reported from quiet runs.
"""
import json
import os
import subprocess
import sys
import threading
import time

UNIT = os.environ.get("CH_UNIT", "mongod-ch")
PORT = os.environ.get("CH_PORT", "15451")
HERE = os.path.dirname(os.path.abspath(__file__))
ORDERS = os.environ.get("S2_ORDERS", "alternating,blocked_CE,blocked_EC,shuffled").split(",")
ARMS = ["docs"]   # one collection; the permutation is the only variable here
REPS = int(os.environ.get("S2_REPS", "3"))


def cgroup():
    out = subprocess.run(["systemctl", "--user", "show", "-p", "ControlGroup",
                          "--value", f"{UNIT}.service"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if not out:
        sys.exit(f"unit {UNIT}.service has no cgroup; run tools/harness/start_mongod_cgroup.sh")
    return "/sys/fs/cgroup" + out


CG = cgroup()


def read(path, key=None):
    with open(path) as fh:
        txt = fh.read()
    if key is None:
        return int(txt.strip())
    for line in txt.splitlines():
        if line.startswith(key):
            return int(line.split()[1])
    raise KeyError(key)


class PeakSampler(threading.Thread):
    def __init__(self, path, interval=0.01):
        super().__init__(daemon=True)
        self.path, self.interval, self.peak, self._done = path, interval, 0, False

    def run(self):
        while not self._done:
            try:
                self.peak = max(self.peak, read(self.path))
            except OSError:
                pass
            time.sleep(self.interval)

    def stop(self):
        self._done = True
        self.join(timeout=2)
        return self.peak


def phase(arm, order, rep):
    env = dict(os.environ, S2_QUIET="1", S2_COLL=arm, S2_ORDERS=order, S2_REP=str(rep))
    mem0 = read(f"{CG}/memory.current")
    sampler = PeakSampler(f"{CG}/memory.current")
    sampler.start()
    cpu0 = read(f"{CG}/cpu.stat", "usage_usec")
    t0 = time.monotonic()
    out = subprocess.run(["mongosh", "--quiet", "--port", PORT, "--file",
                          os.path.join(HERE, "s79039_order.js")],
                         capture_output=True, text=True, check=False, env=env)
    wall = time.monotonic() - t0
    cpu1 = read(f"{CG}/cpu.stat", "usage_usec")
    peak = sampler.stop()
    rec = {}
    for line in out.stdout.splitlines():
        if "@@JSON@@" in line:
            rec = json.loads(line.replace("@@JSON@@", ""))
    c = rec.get("counters") or {}
    return {"arm": arm, "order": order, "rep": rep,
            "cpu_ms": (cpu1 - cpu0) / 1000.0, "wall_s": wall,
            "peak_mb": peak / 1048576.0, "rise_mb": (peak - mem0) / 1048576.0,
            "docs": c.get("executor_scanned_docs"), "keys": c.get("executor_scanned_keys"),
            "replans": c.get("replanned"), "mp_micros": c.get("mp_micros"),
            "final": rec.get("final_cache")}


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def main():
    rows = [phase(a, o, r) for a in ARMS for o in ORDERS for r in range(REPS)]
    print(f"mongod cgroup: {CG}")
    print(f"identical multiset per row; ONLY the arrival order differs.")
    print(f"{REPS} repeats per cell, reported mean +- sd.\n")
    print(f"{'arm':<9} {'order':<12} {'CPU ms':>16} {'wall s':>14} {'docs scanned':>20} "
          f"{'optimizer us':>18} {'replans':>10} {'peak RSS MB':>14}")
    print("-" * 132)
    cells = {}
    for arm in ARMS:
        for o in ORDERS:
            g = [r for r in rows if r["arm"] == arm and r["order"] == o]
            cells[(arm, o)] = g
            f = lambda k, w=10: f"{mean([x[k] for x in g]):>{w},.1f}+-{sd([x[k] for x in g]):,.1f}"
            print(f"{arm:<9} {o:<12} {f('cpu_ms'):>16} {f('wall_s',7)+'':>14} "
                  f"{f('docs',13):>20} {f('mp_micros',11):>18} {f('replans',4):>10} "
                  f"{f('peak_mb',7):>14}")

    for arm in ARMS:
        g = [r for r in rows if r["arm"] == arm]
        if len(ORDERS) < 2:
            continue
        per = {o: mean([r["cpu_ms"] for r in g if r["order"] == o]) for o in ORDERS}
        hi, lo = max(per, key=per.get), min(per, key=per.get)
        dper = {o: mean([r["docs"] for r in g if r["order"] == o]) for o in ORDERS}
        print(f"\n{arm}: worst order costs {per[hi] / max(per[lo], 1e-9):.2f}x the CPU of the best "
              f"({hi} vs {lo}) for the SAME multiset")
        print(f"  documents scanned: {dper[hi]:,.0f} vs {dper[lo]:,.0f} "
              f"({dper[hi] / max(dper[lo], 1):.1f}x)")
        peaks = [r["peak_mb"] for r in g]
        print(f"  peak RSS across orders: {min(peaks):.1f}-{max(peaks):.1f} MB "
              f"(spread {max(peaks) - min(peaks):+.2f} MB)")
    print("\nCaveat: peak RSS is dominated by the pinned 8 GB WiredTiger cache, so per-query")
    print("structures below a few MB are under the measurement floor. Reported, not assumed away.")
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

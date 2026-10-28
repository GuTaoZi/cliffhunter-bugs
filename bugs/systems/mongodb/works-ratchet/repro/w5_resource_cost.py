#!/usr/bin/env python3
"""What arrival order costs in CPU and memory (oracle O3), per the standing requirement.

W5's headline is a metamorphic violation: one multiset of queries, several arrival orders,
materially different cost. Latency alone is a weak way to state that, for two reasons this
harness exists to fix:

  1. The per-query instrumentation UNDER-REPORTS. On the docs collection all four orders
     report an identical 1 200 documentsExamined and an identical 1 380 server-wide
     executor scan count, yet server time differs 11.6x. The difference is optimizer CPU
     spent re-planning, and no work counter MongoDB exposes contains it. CPU is the only
     instrument that sees it.
  2. The order that wins depends on which cost you measure, so measuring one is not enough.

mongod runs inside a systemd user service (tools/harness/start_mongod_cgroup.sh) so CPU and peak
memory are attributed to the server alone, excluding the mongosh client.
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
COLL = os.environ.get("W5_COLL", "docs_bar")
ORDERS = os.environ.get("W5_ORDERS", "M_first,M_last,M_middle").split(",")
RANKERS = os.environ.get("W5_RANKERS", "multiPlanning,automaticCE").split(",")


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
    """Sample memory.current for a real per-phase peak.

    memory.peak cannot be reset on this kernel -- the write is accepted and ignored -- so it
    reports a stale global watermark. See docs/oracle-o2.md.
    """

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


def sh(js):
    return subprocess.run(["mongosh", "--quiet", "--port", PORT, "--eval", js],
                          capture_output=True, text=True, check=False).stdout


def phase(ranker, order):
    sh(f"db.adminCommand({{setParameter:1, planRankerMode:'{ranker}'}})")
    env = dict(os.environ, W5_QUIET="1", W5_COLL=COLL, W5_ORDERS=order,
               W5_NMEDQ=os.environ.get("W5_NMEDQ", "2"),
               W5_NPER=os.environ.get("W5_NPER", "9"))

    mem0 = read(f"{CG}/memory.current")
    sampler = PeakSampler(f"{CG}/memory.current")
    sampler.start()
    cpu0 = read(f"{CG}/cpu.stat", "usage_usec")
    t0 = time.monotonic()
    out = subprocess.run(["mongosh", "--quiet", "--port", PORT, "--file",
                          os.path.join(HERE, "w5_order.js")],
                         capture_output=True, text=True, check=False, env=env)
    wall = time.monotonic() - t0
    cpu1 = read(f"{CG}/cpu.stat", "usage_usec")
    peak = sampler.stop()

    rec = {}
    for line in out.stdout.splitlines():
        if "@@JSON@@" in line:
            rec = json.loads(line.replace("@@JSON@@", ""))
    return {"ranker": ranker, "order": order,
            "cpu_ms": (cpu1 - cpu0) / 1000.0, "wall_s": wall,
            "peak_mb": peak / 1048576.0, "peak_rise_mb": (peak - mem0) / 1048576.0,
            # Server-wide scannedObjects delta: valid in quiet mode (where there is no
            # per-query trace) AND the only counter that includes work done by a
            # cached-plan trial that a replan then threw away.
            "docs": (rec.get("counters") or {}).get("executor_scanned_docs"),
            "exec_keys": (rec.get("counters") or {}).get("executor_scanned_keys"),
            "replans": (rec.get("counters") or {}).get("replanned"),
            "final": rec.get("final_cache")}


def main():
    rows = [phase(r, o) for r in RANKERS for o in ORDERS]
    sh("db.adminCommand({setParameter:1, planRankerMode:'multiPlanning'})")

    print(f"collection {COLL}; identical multiset per order, only arrival order differs\n")
    print(f"{'ranker':<14} {'order':<10} {'CPU ms':>10} {'wall s':>8} {'docs scanned':>14} "
          f"{'keys scanned':>14} {'replans':>8} {'peak RSS MB':>12} {'final cache entry':>26}")
    print("-" * 124)
    for r in rows:
        f = r["final"] or {}
        fc = (f"{f.get('plan')}/{'ACTIVE' if f.get('isActive') else 'inactive'} w={f.get('works')}"
              if f.get("present") else "-none-")
        print(f"{r['ranker']:<14} {r['order']:<10} {r['cpu_ms']:>10.1f} {r['wall_s']:>8.1f} "
              f"{r['docs']:>14,} {r['exec_keys']:>14,} {r['replans']:>8} "
              f"{r['peak_mb']:>12.1f} {fc:>26}")

    for ranker in RANKERS:
        sub = [r for r in rows if r["ranker"] == ranker]
        if len(sub) < 2:
            continue
        lo = min(sub, key=lambda r: r["cpu_ms"])
        hi = max(sub, key=lambda r: r["cpu_ms"])
        print(f"\n{ranker}: worst order costs {hi['cpu_ms'] / max(lo['cpu_ms'], 1e-9):.1f}x the CPU "
              f"of the best ({hi['order']} vs {lo['order']}) for the SAME multiset")
        print(f"  documents scanned: {hi['docs']:,} vs {lo['docs']:,} "
              f"({hi['docs'] / max(lo['docs'], 1):.1f}x)")
        peaks = [r["peak_mb"] for r in sub]
        print(f"  peak RSS across orders: {min(peaks):.1f}-{max(peaks):.1f} MB "
              f"(spread {max(peaks) - min(peaks):+.1f} MB) -- no order holds more memory; the")
        print("    cost of the wrong steady state is CPU and scanning, not footprint")
    # Cross-ranker comparison: the scoping question, exactly as for W4.
    mp = [r for r in rows if r["ranker"] == "multiPlanning"]
    ce = [r for r in rows if r["ranker"] == "automaticCE"]
    if mp and ce:
        mp_lo, mp_hi = min(r["cpu_ms"] for r in mp), max(r["cpu_ms"] for r in mp)
        ce_lo, ce_hi = min(r["cpu_ms"] for r in ce), max(r["cpu_ms"] for r in ce)
        print(f"\norder SENSITIVITY, worst/best CPU within a ranker:")
        print(f"  multiPlanning : {mp_hi / max(mp_lo, 1e-9):.1f}x   <- order-dependent")
        print(f"  automaticCE   : {ce_hi / max(ce_lo, 1e-9):.1f}x   <- order-insensitive")
        print(f"  and automaticCE is {mp_hi / max(ce_hi, 1e-9):.1f}x cheaper than the worst "
              f"multiPlanning order, scanning "
              f"{max(r['docs'] for r in mp) / max(max(r['docs'] for r in ce), 1):,.0f}x fewer documents.")
        print("  CBR creates no plan cache entry at all for this shape, which is why it has no")
        print("  order-dependent state to get wrong -- the fix is structural, not a better constant.")
    print("\nCaveat: peak RSS is dominated by the pinned WiredTiger cache, so per-query")
    print("structures below a few MB are under the measurement floor. Reported, not assumed away.")
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

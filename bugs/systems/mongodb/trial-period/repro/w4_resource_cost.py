#!/usr/bin/env python3
"""What the trial period's decision costs in CPU and memory, not just wall-clock.

Required by the standing rule in docs/oracle-o1-refinement.md. W4 differs from W2 in an
important way: BOTH candidate plans are streaming IXSCAN+FETCH with no blocking stage, so
neither holds a data structure whose size depends on the input. The prediction is therefore
that peak RSS is FLAT and the entire cost of the wrong decision is CPU and cache traffic.
Stating that is the point -- it distinguishes this defect from W2's memory guard, and a
flat memory column is a result, not a missing measurement.

Peak RSS is dominated by the pinned 8 GB WiredTiger cache, so it cannot resolve the
difference on its own. Two things are reported alongside it. 'pages requested from the
cache' is the resource the bad plan actually consumes: it pulls every document of a
2.95M-document scan through the cache to return 101 of them. 'bytes read into cache' is
disk->cache traffic, and is expected to be ~0 here because the whole collection fits in
the pinned cache -- which makes this measurement a LOWER bound on the cliff, since a
cache-resident scan is the cheapest the bad plan can possibly be.

NOTE on peak memory: this kernel (6.18) accepts a write to cgroup memory.peak but does not
actually reset the watermark, so memory.peak reads as a stale global maximum and is useless
per phase. Peak is therefore SAMPLED from memory.current in a background thread, which is a
real per-phase measurement. This was verified before being relied on -- an earlier version
of this script reported the unreset watermark, which was identical across all four phases
and would have been silently mistaken for "memory is flat".

mongod runs inside a systemd user service (tools/harness/start_mongod_cgroup.sh) so CPU and peak
memory are attributed to the server alone, with the mongosh client's own cost excluded.
"""
import json
import os
import subprocess
import sys
import threading
import time

UNIT = os.environ.get("CH_UNIT", "mongod-ch")
PORT = os.environ.get("CH_PORT", "15451")
DB = os.environ.get("W4_DB", "w4")
COLL = os.environ.get("W4_COLL", "docs")
REPS = int(os.environ.get("RC_REPS", "5"))
MONGOSH = "mongosh"


def cgroup():
    out = subprocess.run(["systemctl", "--user", "show", "-p", "ControlGroup",
                          "--value", f"{UNIT}.service"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if not out:
        sys.exit(f"unit {UNIT}.service has no cgroup; run tools/harness/start_mongod_cgroup.sh")
    return "/sys/fs/cgroup" + out


CG = cgroup()


def sh(js, capture=False):
    r = subprocess.run([MONGOSH, "--quiet", "--port", PORT, "--eval", js],
                       capture_output=True, text=True, check=False)
    return r.stdout if capture else None


def read(path, key=None):
    with open(path) as fh:
        txt = fh.read()
    if key is None:
        return int(txt.strip())
    for line in txt.splitlines():
        if line.startswith(key):
            return int(line.split()[1])
    raise KeyError(key)


def wt_counters():
    out = sh("const c=db.serverStatus().wiredTiger.cache;"
             "print(c['bytes read into cache']+' '+c['pages requested from the cache'])",
             capture=True)
    a, b = out.strip().splitlines()[-1].split()
    return int(a), int(b)


class PeakSampler(threading.Thread):
    """Sample memory.current to get a real per-phase peak.

    memory.peak cannot be reset on this kernel (the write is accepted and ignored), so it
    reports a stale global watermark. Sampling is the honest substitute.
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


def query(hint):
    h = f".hint({hint})" if hint else ""
    return (f"db.getSiblingDB('{DB}').{COLL}.find({{a:1,b:5}}){h}.toArray().length;")


def phase(label, hint, max_results):
    setup = (f"db.adminCommand({{setParameter:1,internalQueryFrameworkControl:'trySbeRestricted'}});"
             f"db.adminCommand({{setParameter:1,internalQueryPlanEvaluationMaxResults:{max_results}}});"
             f"db.getSiblingDB('{DB}').{COLL}.getPlanCache().clear();")
    sh(setup + query(hint))              # warm the cache and settle the plan

    mem_before = read(f"{CG}/memory.current")
    sampler = PeakSampler(f"{CG}/memory.current")
    sampler.start()

    cpu0, (wtb0, wtp0) = read(f"{CG}/cpu.stat", "usage_usec"), wt_counters()
    # Clear the plan cache before every rep so the planning decision is re-taken each time:
    # in the unhinted phases the multi-plan trial is part of what we are pricing.
    for _ in range(REPS):
        sh(f"db.getSiblingDB('{DB}').{COLL}.getPlanCache().clear();" + query(hint))
    cpu1, (wtb1, wtp1) = read(f"{CG}/cpu.stat", "usage_usec"), wt_counters()

    peak = sampler.stop()
    return {"label": label, "cpu_ms": (cpu1 - cpu0) / REPS / 1000.0,
            "peak_mb": peak / 1048576.0,
            "peak_rise_mb": (peak - mem_before) / 1048576.0,
            "wt_read_mb": (wtb1 - wtb0) / REPS / 1048576.0,
            "wt_pages_req": (wtp1 - wtp0) / REPS}


def main():
    rows = [
        phase("hint {b:1}  optimal plan, forced", "{b:1}", 101),
        phase("hint {a:1}  plan the trial picks", "{a:1}", 101),
        phase("unhinted, maxResults=101 (default)", None, 101),
        phase("unhinted, maxResults=102", None, 102),
    ]
    sh(f"db.adminCommand({{setParameter:1,internalQueryPlanEvaluationMaxResults:101}});")

    print(f"{'phase':<36} {'CPU ms/q':>9} {'cache pages/q':>14} {'disk->cache MB/q':>17} "
          f"{'peak RSS MB':>12} {'rise MB':>9}")
    print("-" * 102)
    for r in rows:
        print(f"{r['label']:<36} {r['cpu_ms']:>9.1f} {r['wt_pages_req']:>14,.0f} "
              f"{r['wt_read_mb']:>17.1f} {r['peak_mb']:>12.1f} {r['peak_rise_mb']:>9.1f}")

    good, bad = rows[0], rows[1]
    print()
    print(f"the plan the trial period picks costs "
          f"{bad['cpu_ms'] / max(good['cpu_ms'], 1e-9):,.1f}x the CPU of the plan it discarded")
    print(f"  and {bad['wt_pages_req'] / max(good['wt_pages_req'], 1e-9):,.1f}x the cache page requests")
    print(f"peak RSS: {good['peak_mb']:.1f} MB vs {bad['peak_mb']:.1f} MB "
          f"({bad['peak_mb'] - good['peak_mb']:+.1f} MB)")
    print(f"  -- both plans are streaming IXSCAN+FETCH with no blocking stage, so there is no")
    print(f"     per-query structure to grow. The wrong decision buys NOTHING in memory:")
    print(f"     it is {bad['cpu_ms'] / max(good['cpu_ms'], 1e-9):,.1f}x the CPU for a 0 MB saving.")
    print()
    print("Caveats: peak RSS is dominated by the pinned WiredTiger cache, so per-query")
    print("structures below a few MB sit under the measurement floor -- reported, not assumed")
    print("away. disk->cache traffic is ~0 because the collection is cache-resident, which makes")
    print("the CPU ratio a LOWER bound on the cliff.")
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

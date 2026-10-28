#!/usr/bin/env python3
"""valkey/blind-to-target-overload (queue rank 12): inserts during a hashtable shrink pile into the tiny new table.

Bug (src/hashtable.c): when a large table shrinks, every new entry goes into the new, small table (ht1), and
expansion is blocked while the rehash runs. If ht0 is huge and nearly empty, its rehash is slow (mostly empty
buckets), and a burst of inserts overfills ht1 into long bucket chains. Fixed upstream in 262b371da0d2 (#3175,
2026-02-24): during a shrink, an insert checks ht1's fill and above the hard maximum swaps the tables, aborts the
shrink and rehashes as an expand. Parent 501b3153f26e.

One run (fresh server per run, release builds from tools/reproduce/build.sh), the fix's own test recipe (a sorted
set, tests/unit/type/zset.tcl), larger:
  1. ZADD N members to one sorted set (pipelined batches of 1,000), so its hashtable is large;
  2. ZREMRANGEBYRANK z 1 -1 in one command: every member but one is deleted at once, so the table shrinks to the
     minimal ht1 (7 entries) with the rehash of the huge, empty ht0 just started (removing members one by one, as
     a first version of this script did, lets each removal advance the rehash, and the shrink finishes before
     the burst);
  3. measured: a burst of M new members, ZADD in pipelined batches of 100; each batch's round-trip latency,
     the burst's wall time, server CPU and peak RSS over the burst (tools/reproduce/measure.py's Sampler);
  4. DEBUG HTSTATS-KEY before and after the burst (rehashing state, table sizes, chain lengths).
Arms alternate per repetition.

    run.py build | measure [REPS] | report
"""
import json
import os
import re
import statistics as st
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../.."))
sys.path.insert(0, f"{REPO}/tools/reproduce")
from measure import Sampler  # noqa: E402
from respclient import Resp, start, stop  # noqa: E402

ARMS = {"parent": "501b3153f26e", "fix": "262b371da0d2"}
PORT = 15426
N, KEEP, M = int(os.environ.get("N", 2_000_000)), 1, int(os.environ.get("M", 200_000))


def server(arm):
    return f"{ROOT}/build/valkey-{ARMS[arm]}/src/src/valkey-server"


def build():
    for arm, sha in ARMS.items():
        r = subprocess.run(["sh", f"{REPO}/tools/reproduce/build.sh", "valkey", sha], capture_output=True, text=True)
        print(arm, sha, "rc", r.returncode, r.stdout.strip().split("\n")[-1][:120])


def htstats(r):
    txt = r.cmd("DEBUG", "HTSTATS-KEY", "z", "full")
    txt = txt.decode(errors="replace") if isinstance(txt, bytes) else str(txt)
    return " | ".join(l.strip() for l in txt.splitlines() if l.strip())[:600]


def batches(prefix, lo, hi, size):
    for a in range(lo, hi, size):
        args = []
        for i in range(a, min(hi, a + size)):
            args += [str(i), f"{prefix}{i}"]
        yield [["ZADD", "z", *args]]


def one(arm, rep):
    log = open(f"{D}/logs/{arm}-r{rep}.log", "w")
    p = start(server(arm), PORT, ["--enable-debug-command", "yes"], log)   # DEBUG HTSTATS-KEY needs it
    try:
        r = Resp(PORT, timeout=600)
        t0 = time.time()
        for c in batches("m", 0, N, 1000):
            r.send(c)
        fill_s = time.time() - t0
        t0 = time.time()
        r.cmd("ZREMRANGEBYRANK", "z", "1", "-1")
        remove_s = time.time() - t0
        before = htstats(r)
        sampler = Sampler(p.pid)
        sampler.poll()
        sampler.start()
        lat = []
        t0 = time.time()
        for c in batches("n", 0, M, 100):
            b0 = time.perf_counter()
            r.send(c)
            lat.append((time.perf_counter() - b0) * 1e6)
        burst_s = time.time() - t0
        sampler.stop.set()
        sampler.join()
        sampler.poll()
        after = htstats(r)
        card = int(r.cmd("ZCARD", "z"))
        lat.sort()
        q = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))]  # noqa: E731
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "N": N, "KEEP": KEEP, "M": M, "fill_s": round(fill_s, 2),
                "remove_s": round(remove_s, 2), "burst_s": round(burst_s, 3),
                "inserts_per_s": round(M / burst_s), "batch_us_p50": round(q(0.5), 1), "batch_us_p99": round(q(0.99), 1),
                "batch_us_max": round(lat[-1], 1), "batch_us_mean": round(st.mean(lat), 1),
                "server_cpu_s": round(sampler.cpu_s(), 3), "server_peak_rss_mb": round(sampler.peak / 1024, 1),
                "scard": card, "htstats_before": before, "htstats_after": after}
    finally:
        stop(p)
        log.close()


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    os.makedirs(f"{D}/logs", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in ("arm", "rep", "burst_s", "inserts_per_s", "batch_us_p50",
                                                      "batch_us_p99", "batch_us_max", "server_cpu_s",
                                                      "server_peak_rss_mb")}), flush=True)


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["burst_s", "inserts_per_s", "batch_us_p50", "batch_us_p99", "batch_us_max", "server_cpu_s",
            "server_peak_rss_mb", "fill_s", "remove_s"]
    out = [f"# valkey blind-to-target-overload: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"One sorted set: {rows[0]['N']:,} members added, all but {rows[0]['KEEP']} removed by one "
           f"ZREMRANGEBYRANK, then a burst of {rows[0]['M']:,} new members in pipelined ZADD batches of 100 "
           "(measured). mean, sd [min, max].", "",
           "| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [r[k] for r in rows if r["arm"] == arm]
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {means['parent'] / means['fix']:.2f} |")
    for arm in ("parent", "fix"):
        r = next(r for r in rows if r["arm"] == arm)
        out += ["", f"{arm}, before the burst: `{r['htstats_before']}`", "", f"{arm}, after: `{r['htstats_after']}`"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"build": build, "measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5),
     "report": report}[sys.argv[1]]()

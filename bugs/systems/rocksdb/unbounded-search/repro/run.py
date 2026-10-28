#!/usr/bin/env python3
"""rocksdb/unbounded-search: buggy parent vs fix, HyperClockCache with most entries pinned.

Bug (cache/clock_cache.cc): eviction sweeps the clock until enough unpinned space is freed. With
nearly all entries pinned there was no bound on the sweep, so each insert could burn CPU scanning.
Fixed by 88bc91f3cc2b (2023-12-14), which caps eviction effort (eviction_effort_cap).

Each run: cache_bench -cache_type=auto_hyper_clock_cache -threads=12 -histograms=0 -pinned_ratio=1.7
(the commit's own stress case), measured with tools/reproduce/runcmd.py (CPU and peak RSS of the benchmark,
which is the cache). Records "Rough parallel ops/sec". Arms alternate; buggy repeated last.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
ARMS = {"buggy": f"{ROOT}/build/rocksdb-cd577f605948/src/cache_bench",
        "fixed": f"{ROOT}/build/rocksdb-88bc91f3cc2b/src/cache_bench"}
ARGS = ["-cache_type=auto_hyper_clock_cache", "-threads=12", "-histograms=0", "-pinned_ratio=1.7"]


def one(arm, rep):
    out = os.path.join(REPO, "data", "experiments", "rocksdb-unbounded-search", "raw", f"{arm}-{rep}.txt")
    m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "runcmd.py"), out, "--", ARMS[arm], *ARGS],
                       capture_output=True, text=True)
    return parse(json.loads(m.stdout), arm, rep)


def parse(rec, arm, rep):
    txt = open(os.path.join(REPO, "data", "experiments", "rocksdb-unbounded-search", "raw", f"{arm}-{rep}.txt")).read()
    ops = re.search(r"Rough parallel ops/sec = (\d+)", txt)
    rec.update({"arm": arm, "rep": rep, "ops_per_s": int(ops.group(1)) if ops else None,
                "cpu_per_mop_s": None})
    nops = re.search(r"Ops per thread\s*:\s*(\d+)", txt)
    thr = re.search(r"Number of threads\s*:\s*(\d+)", txt)
    if nops and thr:
        total = int(nops.group(1)) * int(thr.group(1))
        rec["total_ops"] = total
        rec["cpu_per_mop_s"] = rec["cpu_s"] / (total / 1e6)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--reparse", action="store_true", help="re-read raw/*.txt into raw/runs.jsonl, no new runs")
    a = ap.parse_args()
    if a.reparse:
        path = os.path.join(REPO, "data", "experiments", "rocksdb-unbounded-search", "raw", "runs.jsonl")
        recs = [parse(json.loads(l), json.loads(l)["arm"], json.loads(l)["rep"]) for l in open(path)]
        with open(path, "w") as out:
            out.writelines(json.dumps(r) + "\n" for r in recs)
        return
    os.makedirs(os.path.join(REPO, "data", "experiments", "rocksdb-unbounded-search", "raw"), exist_ok=True)
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "rocksdb-unbounded-search", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, rep)
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"ops/s {rec['ops_per_s']}", f"wall {rec['wall_s']}s", f"cpu {rec['cpu_s']}s",
                  f"cpu/Mop {rec['cpu_per_mop_s']}", f"peak {rec['peak_rss_mb']}MB", flush=True)


if __name__ == "__main__":
    main()

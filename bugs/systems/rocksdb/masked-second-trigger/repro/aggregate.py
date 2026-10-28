#!/usr/bin/env python3
"""Aggregate results/NAME-ARM-i.json into per-arm mean, sd and range.

    aggregate.py NAME     (e.g. main, long)
"""
import os
import glob
import json
import statistics
import sys

name = sys.argv[1] if len(sys.argv) > 1 else "main"
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
KEYS = ["write_mb_s", "lat_mean_us", "lat_p50_us", "lat_p99_us", "lat_p999_us", "lat_max_ms",
        "cpu_s", "cpu_us_per_op", "peak_rss_mb", "peak_memtables_mb", "peak_active_memtables_mb",
        "memtables_mb_at_30s", "memtables_mb_at_60s", "memtables_mb_at_90s", "memtables_mb_at_180s",
        "frac_samples_active_ge_limit", "peak_num_immutable", "stall_s",
        "log_wal_branch_flushes", "log_mem_branch_flushes", "log_slowdown_writes", "log_stop_writes",
        "flushes_started", "flushed_memtable_mb_mean", "mb_written", "errors"]
arms = {}
for f in sorted(glob.glob(f"{D}/{name}-*-*.json")):
    r = json.loads(open(f).read())
    arms.setdefault(r["tag"].split("-")[1], []).append(r)
order = [a for a in ("parent", "fix") if a in arms]
print(f"# {name}: " + ", ".join(f"{a} n={len(arms[a])} ({arms[a][0]['arm']})" for a in order))
print("| metric | " + " | ".join(f"{a} mean (sd) [min-max]" for a in order) + " |")
print("|---|" + "---|" * len(order))
for k in KEYS:
    cells = []
    for a in order:
        v = [r[k] for r in arms[a] if k in r]
        if not v:
            cells.append("-")
            continue
        m = statistics.mean(v)
        sd = statistics.stdev(v) if len(v) > 1 else 0.0
        cells.append(f"{m:.4g} ({sd:.2g}) [{min(v):.4g}-{max(v):.4g}]")
    print(f"| {k} | " + " | ".join(cells) + " |")

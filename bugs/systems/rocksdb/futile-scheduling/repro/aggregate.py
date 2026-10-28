#!/usr/bin/env python3
"""aggregate.py PREFIX -> markdown tables (mean and sample sd over repetitions) per config and arm,
from results/PREFIX-*.json."""
import glob
import json
import os
import statistics as st
import sys

D = os.path.dirname(os.path.abspath(__file__))
pfx = sys.argv[1] if len(sys.argv) > 1 else "main"
runs = {}
for p in sorted(glob.glob(f"{D}/results/{pfx}-*.json")):
    d = json.loads(open(p).read().strip().splitlines()[-1])
    if d.get("rc") != 0 or "error" in d:
        print(f"skip {p}: rc={d.get('rc')} {d.get('error','')}")
        continue
    _, cfg, arm, rep = os.path.basename(p)[:-5].split("-")
    runs.setdefault(cfg, {}).setdefault(arm, []).append(d)

METRICS = [
    ("put mean us", lambda d: d["put"]["mean_us"]),
    ("put p99 us", lambda d: d["put"]["p99_us"]),
    ("put p99.9 us", lambda d: d["put"]["p999_us"]),
    ("delete p99 us", lambda d: d["delete"]["p99_us"]),
    ("GetSnapshot mean us", lambda d: d["get_snapshot"]["mean_us"]),
    ("GetSnapshot p99 us", lambda d: d["get_snapshot"]["p99_us"]),
    ("ReleaseSnapshot mean us", lambda d: d["release_snapshot"]["mean_us"]),
    ("ReleaseSnapshot p99 us", lambda d: d["release_snapshot"]["p99_us"]),
    ("ReleaseSnapshot p99.9 us", lambda d: d["release_snapshot"]["p999_us"]),
    ("pairs/s achieved", lambda d: d["pairs_per_s"]),
    ("snapshots/s achieved", lambda d: d["snaps_per_s"]),
    ("process CPU s (20 s window)", lambda d: d["cpu_s"]),
    ("CPU s, rocksdb:low (compaction pool)", lambda d: d["thread_cpu_s"].get("rocksdb:low", 0)),
    ("CPU s, rocksdb:high (flush pool)", lambda d: d["thread_cpu_s"].get("rocksdb:high", 0)),
    ("CPU s, snapshot threads", lambda d: d["thread_cpu_s"].get("snap", 0)),
    ("CPU s, writer thread", lambda d: d["thread_cpu_s"].get("writer", 0)),
    ("peak RSS MB (window)", lambda d: d["peak_rss_mb"]),
    ("process max RSS MB", lambda d: d["process_maxrss_mb"]),
    ("compaction jobs scheduled (LOW)", lambda d: d["low_jobs"]),
    ("'Compaction nothing to do' in LOG", lambda d: d["log"]["nothing_to_do"]),
    ("flushes", lambda d: d["flushes"]),
    ("futile jobs per flush", lambda d: d["log"]["nothing_to_do"] / max(1, d["flushes"])),
    ("futile jobs per 1000 releases", lambda d: 1000 * d["log"]["nothing_to_do"] / max(1, d["release_snapshot"]["n"])),
    ("db mutex wait us (kAll only)", lambda d: d["db_mutex_wait_us"]),
    ("voluntary ctx switches", lambda d: d["vol_ctxsw"]),
]


def fmt(v):
    return f"{v:.3f}" if abs(v) < 100 else f"{v:.0f}"


for cfg in sorted(runs):
    arms = runs[cfg]
    names = [a for a in ("parent", "fix") if a in arms]
    print(f"\n### {pfx} / {cfg}  (n = " + ", ".join(f"{a} {len(arms[a])}" for a in names) + ")\n")
    print("| metric | " + " | ".join(f"{a} mean ± sd [min–max]" for a in names) + " | parent/fix |")
    print("|---|" + "---|" * len(names) + "---|")
    for name, f in METRICS:
        cells, means = [], []
        for a in names:
            xs = [f(d) for d in arms[a]]
            m = st.mean(xs)
            sd = st.stdev(xs) if len(xs) > 1 else 0.0
            means.append(m)
            cells.append(f"{fmt(m)} ± {fmt(sd)} [{fmt(min(xs))}–{fmt(max(xs))}]")
        ratio = (f"{means[0] / means[1]:.2f}" if len(means) == 2 and means[1] else "–")
        print(f"| {name} | " + " | ".join(cells) + f" | {ratio} |")

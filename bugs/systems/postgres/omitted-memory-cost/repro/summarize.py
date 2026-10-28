#!/usr/bin/env python3
"""Markdown tables from results/<variant>.jsonl: per arm, mean, sample stdev and [min, max] over the repetitions,
and the per-repetition ratio parent/fix (paired by repetition).   summarize.py A B C"""
import os
import json
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = [("wall_s", "latency, wall (s)"), ("exec_ms", "latency, Execution Time (ms)"), ("cpu_s", "server CPU (s)"),
          ("peak_rss_mb", "peak RSS, VmHWM (MB)"), ("peak_rss_anon_mb", "peak private RssAnon (MB)"),
          ("batches_orig", "batches planned"), ("batches", "batches at end"), ("temp_files", "temp files"),
          ("temp_mb", "temp file MB"), ("hash_mem_usage_kb", "EXPLAIN Memory Usage (kB)")]
ARMS = {"P": "parent 8b886a4e3488", "F": "fix a1b4f289beec"}


def fmt(x):
    return f"{x:,.0f}" if abs(x) >= 100 else (f"{x:.2f}" if abs(x) >= 1 else f"{x:.3f}")


def cell(xs):
    if len(xs) < 2:
        return fmt(xs[0]) if xs else "-"
    return f"{fmt(st.mean(xs))} ± {fmt(st.stdev(xs))} [{fmt(min(xs))}, {fmt(max(xs))}]"


for v in sys.argv[1:]:
    rows = [json.loads(ln) for ln in open(f"{HERE}/results/{v}.jsonl")]
    by = {a: sorted([r for r in rows if r["arm"] == a], key=lambda r: r["rep"]) for a in ARMS}
    p = rows[0]["params"]
    print(f"### Variant {v}: hashed side {p['n_distinct']:,} distinct keys + {p['n_dup']:,} copies of key "
          f"{p['dup_key']} ({p['order']}), probe side {p['n_outer']:,} distinct keys, work_mem={p['work_mem']}; "
          f"n = {len(by['P'])} / {len(by['F'])} repetitions\n")
    print("| metric | " + " | ".join(ARMS[a] for a in ARMS) + " | parent / fix, per rep (mean [min, max]) |")
    print("|---|---|---|---|")
    for f, label in FIELDS:
        cols = [cell([r[f] for r in by[a] if f in r]) for a in ARMS]
        ratios = [rp[f] / rf[f] for rp, rf in zip(by["P"], by["F"]) if rf.get(f)]
        rc = f"{st.mean(ratios):.1f} [{min(ratios):.1f}, {max(ratios):.1f}]" if ratios else "-"
        print(f"| {label} | " + " | ".join(cols) + f" | {rc} |")
    jr = {a: sorted({r.get("join_rows") for r in by[a]}) for a in ARMS}
    print(f"\njoin rows: {jr}; hash cond: {sorted({r.get('hash_cond') for r in rows})}\n")

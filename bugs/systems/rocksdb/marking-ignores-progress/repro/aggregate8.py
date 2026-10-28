#!/usr/bin/env python3
"""Rank 8 (rocksdb/marking-ignores-progress), third setup: results/r8c-<sha>-r<N>.json -> results-rank8.md."""
import glob
import json
import os
import statistics as st

D = os.path.dirname(os.path.abspath(__file__))
P, F = "6dbb6f30e604", "f7b791b213b2"
KEYS = ["compactions_in_window", "compaction_output_mb_in_window", "cpu_s", "peak_rss_mb", "manifest_bytes_before",
        "manifest_bytes_after"]
rows = {a: [json.loads(open(p).read()) for p in sorted(glob.glob(f"{D}/results/r8c-{s}-r*.json"))]
        for a, s in (("parent", P), ("fix", F))}
out = [f"# rank 8, rocksdb/marking-ignores-progress: parent {P} vs fix {F}", "",
       "preserve_internal_time_seconds=100, writes spread over 20 s, the file moved to the last level (6); then 30 s "
       "with no requests. mean, sd [min, max] over 5 runs per arm.", "", "| metric | parent | fix |", "|---|---|---|"]
for k in KEYS:
    cells = []
    for a in ("parent", "fix"):
        v = [x[k] for x in rows[a]]
        cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
    out.append(f"| {k} | {cells[0]} | {cells[1]} |")
out.append(f"| compaction reasons (reason:count) | {rows['parent'][0]['reasons_total']} | {rows['fix'][0]['reasons_total']} |")
open(f"{D}/results-rank8.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))

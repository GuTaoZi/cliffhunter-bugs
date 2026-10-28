#!/usr/bin/env python3
"""Ranks 9 and 8: mean, sd [min, max] per arm over results/r9-*.json and results/r8-*.json -> results.md."""
import glob
import json
import os
import statistics as st

D = os.path.dirname(os.path.abspath(__file__))
RANKS = {"r9": ("rank 9, rocksdb/marking-ignores-progress-3 (allow_ingest_behind)", "00d697bdc532", "eca47fb6960e"),
         "r8": ("rank 8, rocksdb/marking-ignores-progress (preserve_internal_time_seconds=10000)", "6dbb6f30e604",
                "f7b791b213b2")}
KEYS = ["compactions_in_window", "compaction_output_mb_in_window", "cpu_s", "peak_rss_mb", "manifest_bytes_after"]
out = ["# Bottommost-files compaction loops: parent vs fix, 30 s idle window after the setup", "",
       "Setup: 100,000 keys of 1,000 B written twice, flushed, moved to L1, one more key flushed, a snapshot taken "
       "and released; then 30 s with no requests. mean, sd [min, max] over 5 runs per arm."]
for r, (title, parent, fix) in RANKS.items():
    out += ["", f"## {title}: parent {parent} vs fix {fix}", "", "| metric | parent | fix |", "|---|---|---|"]
    rows = {a: [json.loads(open(p).read()) for p in sorted(glob.glob(f"{D}/results/{r}-{s}-r*.json"))]
            for a, s in (("parent", parent), ("fix", fix))}
    for k in KEYS:
        cells = []
        for a in ("parent", "fix"):
            v = [x[k] for x in rows[a]]
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})" if v else "-")
        out.append(f"| {k} | {cells[0]} | {cells[1]} |")
    out.append(f"| compaction reasons (all runs, reason:count) | {rows['parent'][0]['reasons_total']} | "
               f"{rows['fix'][0]['reasons_total']} |")
open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))

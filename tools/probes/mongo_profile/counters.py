#!/usr/bin/env python3
"""The order scripts' own records (the @@JSON@@ line of each OUT/<bug>-<arm>-r<rep>.log): time, documents examined
and the server's plan-cache counters, per run. Writes OUT/counters.md and prints it.

    python3 tools/probes/mongo_profile/counters.py OUT"""
import glob
import json
import os
import re
import sys

O = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
KEYS = ["hits", "misses", "replanned", "evicted", "inactive_replaced", "mp_count", "mp_micros", "mp_works"]
runs = {json.loads(l)["bug"] + "-" + json.loads(l)["arm"] + "-r" + str(json.loads(l)["rep"]): json.loads(l)
        for l in open(f"{O}/runs.jsonl")}
out = ["| run | wall s | server CPU s | peak RSS MB | query millis | docs examined | " + " | ".join(KEYS) + " | final cache entry |",
       "|---" * (7 + len(KEYS)) + "|"]
for p in sorted(glob.glob(f"{O}/s*-r*.log")):
    tag = os.path.basename(p)[:-4]
    line = next((l for l in open(p) if "@@JSON@@" in l), None)
    if not line:
        continue
    d = json.loads(line.split("@@JSON@@", 1)[1])
    c, r, fc = d.get("counters", {}), runs.get(tag, {}), d.get("final_cache") or {}
    cache = f"{'active' if fc.get('isActive') else 'inactive'}, works {fc.get('works')}, {fc.get('plan')}" if fc else "-"
    out.append(f"| {tag} | {r.get('wall_s')} | {r.get('server_cpu_s')} | {r.get('server_peak_rss_mb')} | {d['total_millis']:,} | "
               f"{d['total_docs_examined']:,} | " + " | ".join(f"{c.get(k):,}" if isinstance(c.get(k), int) else str(c.get(k, "-"))
                                                       for k in KEYS) + f" | {cache} |")
open(f"{O}/counters.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))

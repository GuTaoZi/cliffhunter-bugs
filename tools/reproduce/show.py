#!/usr/bin/env python3
"""Print chosen fields of an experiment summary (from tools/reproduce/summarize.py): per arm mean [min, max] (n),
then the buggy/fixed ratio with its 95% CI.   tools/reproduce/show.py SUMMARY.json FIELD...
"""
import json
import sys

d = json.load(open(sys.argv[1]))
fields = sys.argv[2:]
for arm, v in d["arms"].items():
    parts = []
    for k in fields:
        s = v.get(k)
        if s:
            parts.append(f"{k}={s['mean']:.4g} [{s['min']:.4g}, {s['max']:.4g}]")
    n = next((v[k]["n"] for k in fields if v.get(k)), None)
    print(f"{arm:7s} n={n}  " + "  ".join(parts))
for key, arms in d.items():
    if not key.startswith("ratio_to_"):
        continue
    for arm, v in arms.items():
        parts = []
        for k in fields:
            s = v.get(k)
            if s:
                ci = f" ci[{s['ci95'][0]:.3g}, {s['ci95'][1]:.3g}]" if s.get("ci95") else ""
                parts.append(f"{k}={s['mean']:.3g}{ci}")
        print(f"{arm}/{key[9:]}  " + "  ".join(parts))

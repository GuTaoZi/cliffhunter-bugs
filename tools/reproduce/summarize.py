#!/usr/bin/env python3
"""Summarise an experiment's raw/runs.jsonl by arm: mean, min, max and 95% CI of each numeric field,
and the per-repetition ratio of each arm to a baseline arm.

    tools/reproduce/summarize.py EXPERIMENT_DIR [--baseline fixed] [--runs FILE] [--where KEY=VALUE ...] > summary.json

EXPERIMENT_DIR is the result directory (experiments/reproductions/<bug>/); its raw runs are read from
EXPERIMENT_DIR/raw/ if that exists, else from data/experiments/<bug>/raw/, where the reproductions write them.

--where keeps only runs whose field KEY equals VALUE (compared as text), for files holding several settings.
"""
import argparse
import json
import math
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def stats(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    mu = st.mean(xs)
    h = T95.get(len(xs) - 1, 1.96) * st.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else None
    return {"mean": mu, "min": min(xs), "max": max(xs), "n": len(xs),
            "ci95": [mu - h, mu + h] if h is not None else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--baseline", default="fixed")
    ap.add_argument("--runs", default="runs.jsonl", help="file under raw/")
    ap.add_argument("--where", action="append", default=[], help="KEY=VALUE filter")
    a = ap.parse_args()
    raw = os.path.join(a.dir, "raw")
    if not os.path.isdir(raw):
        raw = os.path.join(ROOT, "data", "experiments", os.path.basename(os.path.normpath(a.dir)), "raw")
    runs = [json.loads(l) for l in open(os.path.join(raw, a.runs))]
    for w in a.where:
        k, v = w.split("=", 1)
        runs = [r for r in runs if str(r.get(k)) == v]
    arms = sorted({r["arm"] for r in runs})
    num = sorted({k for r in runs for k, v in r.items() if isinstance(v, (int, float)) and k not in ("rep", "root_pid")})
    out = {"arms": {arm: {k: stats([r.get(k) for r in runs if r["arm"] == arm]) for k in num} for arm in arms},
           "ratio_to_" + a.baseline: {}}
    base = {r["rep"]: r for r in runs if r["arm"] == a.baseline}
    for arm in arms:
        if arm == a.baseline:
            continue
        out["ratio_to_" + a.baseline][arm] = {
            k: stats([r[k] / base[r["rep"]][k] for r in runs
                      if r["arm"] == arm and r.get(k) is not None and r["rep"] in base and base[r["rep"]].get(k)])
            for k in num}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()

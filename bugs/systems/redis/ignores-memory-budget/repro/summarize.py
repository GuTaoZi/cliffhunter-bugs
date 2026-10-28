#!/usr/bin/env python3
"""Summarize data/<series>/*.result.json + *.insert.json into per-arm markdown tables (mean, sd, min-max).

    summarize.py data/A-lru-4M [data/B-... ...]  > results.md
"""
import glob
import json
import os
import statistics as st
import sys


def row(name, vals, fmt="{:.3g}"):
    m = st.mean(vals)
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    f = lambda v: fmt.format(v)
    return f"| {name} | {f(m)} | {f(sd)} | {f(min(vals))} - {f(max(vals))} |"


def series(d):
    arms = {}
    for p in sorted(glob.glob(os.path.join(d, "*.result.json"))):
        r = json.load(open(p))
        ins = json.load(open(p.replace(".result.json", ".insert.json")))
        tr, mm = ins["trace"], r["maxmemory"]
        lat = ins["lat_series_ms"]
        over = [i for i, x in enumerate(tr) if x["used_memory"] > mm + (1 << 20)]
        rec = None
        if over:
            for x in tr[over[0]:]:
                if x["used_memory"] <= mm + (1 << 20):
                    rec = x["t"] - tr[0]["t"]
                    break
        r["_min_keys"] = min(x["keys"] for x in tr + [ins["final"]])
        r["_slow_batches"] = sum(1 for v in lat if v > 10)
        r["_recover_s"] = rec
        r["_accepted"] = r["k"] - r["oom_rejected"]
        arms.setdefault(r["arm"], []).append(r)
    out = [f"### {os.path.basename(d)}", ""]
    any_r = next(iter(arms.values()))[0]
    out.append(f"policy {any_r['policy']}, N={any_r['n']} keys populated, maxmemory = used_memory + "
               f"{any_r['margin']/2**20:.0f} MiB, K={any_r['k']} SETs in batches of {any_r['batch']}")
    out.append("")
    for arm in ("parent", "fix"):
        rs = arms.get(arm, [])
        if not rs:
            continue
        out += [f"**{arm}** ({rs[0]['binary'].split('/build/')[1].split('/')[0]}), {len(rs)} repetitions", "",
                "| metric | mean | sd | min - max |", "|---|---|---|---|"]
        g = lambda k: [x[k] for x in rs]
        out.append(row("insert phase wall (s)", g("insert_wall_s")))
        out.append(row("batch latency p50 (ms)", g("lat_p50_ms")))
        out.append(row("batch latency p99 (ms)", g("lat_p99_ms")))
        out.append(row("batch latency max (ms)", g("lat_max_ms")))
        out.append(row("batches > 10 ms (count)", g("_slow_batches"), "{:.0f}"))
        out.append(row("server CPU over window (s)", [x["server"]["cpu_s"] for x in rs]))
        out.append(row("server peak RSS over window (MB)", [x["server"]["peak_rss_mb"] for x in rs], "{:.1f}"))
        out.append(row("measured window wall (s)", [x["server"]["wall_s"] for x in rs]))
        out.append(row("peak used_memory over maxmemory (MiB)", [x["trace_max_over_maxmemory"] / 2**20 for x in rs], "{:.2f}"))
        out.append(row("evicted_keys", g("evicted_keys"), "{:.0f}"))
        out.append(row("SETs rejected with OOM", g("oom_rejected"), "{:.0f}"))
        out.append(row("SETs accepted", g("_accepted"), "{:.0f}"))
        out.append(row("lowest key count during run", g("_min_keys"), "{:.0f}"))
        out.append(row("final key count (DBSIZE)", g("dbsize_after"), "{:.0f}"))
        recs = [x["_recover_s"] for x in rs if x["_recover_s"] is not None]
        if recs:
            out.append(row("time until used_memory back within maxmemory+1MiB (s)", recs))
        out.append(f"| db0 bucket array(s) before -> after | {rs[0]['table_sizes_before']} -> "
                   f"{sorted(set(str(x['table_sizes_after']) for x in rs))} | | |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print("\n".join(series(d) for d in sys.argv[1:]))

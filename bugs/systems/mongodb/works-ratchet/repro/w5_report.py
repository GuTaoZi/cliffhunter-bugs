#!/usr/bin/env python3
"""Render the W5 order-permutation experiment (oracle O3).

O3's relation needs no cost model: a fixed multiset of queries should reach the same steady
state and cost about the same, whatever order it arrives in. So the report is organised
around DIFFERENCES BETWEEN ORDERS of an identical multiset, not around a sweep.

Two collections are reported, and the contrast between them is the finding:
  docs      E/H only. The replan bar is set by a cheap instance, so replanning catches the
            bad plan after ~210 works. Cost is order-INSENSITIVE in every work counter --
            and still order-sensitive in server time. That is the control.
  docs_bar  adds class M, a legitimately expensive instance of the SAME query shape. If M
            promotes the cache entry, the bar becomes 10 x 200 001 works -- larger than the
            collection -- and the bad plan becomes permanently immune to replanning.
"""
import json
import sys


def load(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip().replace("@@JSON@@", "")
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def fc(f):
    if not f or not f.get("present"):
        return "-none-"
    return f"{f.get('plan')}/{'ACTIVE' if f.get('isActive') else 'inactive'} w={f.get('works')}"


def main():
    rows = load(sys.argv[1])
    builds = {r["coll"]: r for r in rows if r["kind"] == "w5_build"}
    orders = [r for r in rows if r["kind"] == "w5_order"]
    colls = []
    for r in orders:
        if r.get("coll") not in colls:
            colls.append(r.get("coll"))

    for coll in colls:
        sub = [r for r in orders if r.get("coll") == coll]
        b = builds.get(coll)
        print(f"\n{'=' * 112}")
        print(f"== collection {coll}")
        if b:
            print(f"   {b['n']:,} docs. a=0 -> {b['a0_count']:,} docs; b=0 -> {b['b0_count']:,} docs; "
                  f"{b['nrare']:,} rare values x {b['per_rare']} docs per class")
            print(f"   E find({{a:i,b:0}}) -> {b['e_match']} results | "
                  f"H find({{a:0,b:j}}) -> {b['h_match']} results"
                  + (f" | M find({{a:{9001},b:{9002}}}) -> {b['m_match']} results "
                     f"(a=MA {b['ma_count']:,} docs, b=MB {b['mb_count']:,} docs)"
                     if b.get("medium") else ""))
            print(f"   getting the plan wrong costs {b['wrong_plan_ratio']:,.0f}x the documents, per query")
        s0 = sub[0]
        print(f"   multiset per epoch: {s0['nper']} E + {s0['nper']} H"
              + (f" + {s0['nmedq']} M" if s0.get("nmedq") else "")
              + f", x{s0['epochs']} epochs = {s0['n_queries']} queries")
        print(f"   ALL orders below are permutations of that identical multiset")
        print(f"{'=' * 112}")

        print(f"\n  {'order':<12} {'docs (profiler)':>16} {'docs (executor)':>16} {'server ms':>10} "
              f"{'replans':>8} {'catastrophic':>13} {'final cache entry':>24}")
        print("  " + "-" * 104)
        for r in sub:
            c = r["counters"]
            print(f"  {r['order']:<12} {r['total_docs_examined']:>16,} {c['executor_scanned_docs']:>16,} "
                  f"{r['total_millis']:>10,} {c['replanned']:>8} {r['n_catastrophic']:>13} "
                  f"{fc(r['final_cache']):>24}")

        # The O3 verdict, computed rather than asserted.
        def spread(key):
            vals = [key(r) for r in sub]
            lo = min(v for v in vals if v is not None) or 1
            return max(vals) / max(lo, 1)

        print(f"\n  O3 relation (a fixed multiset should be order-insensitive):")
        for label, key in [("documents scanned", lambda r: r["counters"]["executor_scanned_docs"]),
                           ("server time", lambda r: r["total_millis"]),
                           ("replan count", lambda r: max(r["counters"]["replanned"], 1))]:
            sp = spread(key)
            verdict = "HOLDS" if sp < 1.15 else f"VIOLATED, {sp:.1f}x"
            print(f"    {label:<20} worst/best = {sp:6.1f}x   -> {verdict}")
        states = {fc(r["final_cache"]) for r in sub}
        print(f"    final cache state    {len(states)} distinct across {len(sub)} orders"
              f"       -> {'HOLDS' if len(states) == 1 else 'VIOLATED'}")
        if len(states) > 1:
            for r in sub:
                print(f"        {r['order']:<12} -> {fc(r['final_cache'])}")

        if any(r.get("by_class") for r in sub):
            print(f"\n  where the cost lands, by parameter class (documents examined):")
            classes = sorted({k for r in sub for k in (r.get("by_class") or {})})
            print(f"    {'order':<12} " + " ".join(f"{c:>16}" for c in classes))
            for r in sub:
                cells = []
                for c in classes:
                    d = (r.get("by_class") or {}).get(c)
                    cells.append(f"{d['docs']:>14,}/{d['n']:<2}" if d else " " * 16)
                print(f"    {r['order']:<12} " + " ".join(cells))
            print("    (cells are 'documents examined / number of queries' for that class)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

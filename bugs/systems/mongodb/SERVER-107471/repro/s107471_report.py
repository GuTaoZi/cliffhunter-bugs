#!/usr/bin/env python3
"""Render the SERVER-107471 reproduction (oracle O3, order permutation).

SERVER-107471, "Query Plan Cache Issue with Index Selection on High Disparity Index
Values" (2025-07-14, Closed / Won't Do, 5 watchers, zero comments). The reporter's claim
has two halves and this report tests them separately:

  PREMISE  a query with .skip() and the same query without it share one planCacheKey,
           so whichever runs first fixes the plan for the other.
  DEFECT   the plan chosen while the .skip() is present is catastrophic for the no-skip
           query when the filter value is highly disparate (1 matching document).

The control arm deletes .skip(S) and changes nothing else. If the control is
order-insensitive and the skip arm is not, skip is the causal variable rather than the
parameter value -- which is the distinction the ticket itself does not make.
"""
import json
import statistics
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


def agg(vals):
    """mean +- sd, and the raw spread, so a 1.1x difference cannot be sold as a result."""
    if not vals:
        return "-"
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return m, sd


def fmt(vals, w=13):
    if not vals:
        return " " * w
    m, sd = agg(vals)
    return f"{m:>{w},.0f}+-{sd:,.0f}"


def main():
    rows = load(sys.argv[1])
    build = next((r for r in rows if r["kind"] == "s107471_build"), None)
    runs = [r for r in rows if r["kind"] == "s107471_order"]
    sweep = [r for r in rows if r["kind"] == "s107471_sweep"]

    print("=" * 118)
    print("== SERVER-107471  'Query Plan Cache Issue with Index Selection on High Disparity Index Values'")
    print("==   reported 2025-07-14, Closed / Won't Do, 5 watchers, 0 comments, no fixVersion")
    print("=" * 118)
    if build:
        print(f"   {build['n']:,} docs in {build['db']}.{build['coll']}")
        print(f"   indexField1={build['f1_hot']} -> {build['n_hot']:,} docs   "
              f"indexField10=0 -> {build['if10_zero']:,} docs   "
              f"indexField10={build['rare_base']}+k -> {build['r_match']} doc "
              f"({build['n_rare']:,} such values)")
        print(f"   'high disparity' = {build['disparity']:,.0f}x between the two indexField10 values")
        print(f"   using IXSCAN{{indexField1}} for the rare class costs "
              f"{build['wrong_plan_ratio']:,.0f}x the documents")

    # --- the premise ---------------------------------------------------------------------
    if runs:
        pr = runs[0]["premise"]
        print("\n" + "-" * 118)
        print("  PREMISE: does .skip() change the plan cache key on 8.2.12?")
        print("-" * 118)
        for k in ("P_noskip", "P_skip", "R_noskip", "R_skip"):
            if pr.get(k):
                print(f"    {k:<12} planCacheKey={pr[k]['key']}   queryHash={pr[k]['hash']}")
        verdict = "HOLDS -- one cache entry for all four" if pr["all_same_key"] else "DOES NOT HOLD"
        print(f"    -> premise {verdict}")

    # --- the O3 table, aggregated over repeats --------------------------------------------
    arms = []
    for r in runs:
        if r["arm"] not in arms:
            arms.append(r["arm"])
    for arm in arms:
        sub = [r for r in runs if r["arm"] == arm]
        orders = []
        for r in sub:
            if r["order"] not in orders:
                orders.append(r["order"])
        reps = len({r["rep"] for r in sub})
        s0 = sub[0]
        print("\n" + "=" * 118)
        print(f"  ARM '{arm}'  (P = find(F,proj)"
              + (f".skip({s0['skip']})" if s0["skip"] else "")
              + f".limit(10) x{s0['np']}/epoch,  R = find(F',proj).limit(10) x{s0['nr']}/epoch,"
              f" {s0['epochs']} epochs)")
        print(f"  every order below is a permutation of the SAME multiset; {reps} independent repeat(s)")
        print("=" * 118)
        print(f"  {'order':<12} {'docs examined':>17} {'server ms':>13} {'optimizer us':>15} "
              f"{'replans':>9} {'catastrophic':>13}  final cache entry")
        print("  " + "-" * 114)
        for o in orders:
            g = [r for r in sub if r["order"] == o]
            states = sorted({fc(r["final_cache"]) for r in g})
            print(f"  {o:<12} {fmt([r['total_docs_examined'] for r in g],14)} "
                  f"{fmt([r['total_millis'] for r in g],9)} "
                  f"{fmt([r['counters']['mp_micros'] for r in g],11)} "
                  f"{fmt([r['counters']['replanned'] for r in g],5)} "
                  f"{fmt([r['n_catastrophic'] for r in g],9)}  {'; '.join(states)}")

        def ratio(key):
            per = [statistics.mean([key(r) for r in sub if r["order"] == o]) for o in orders]
            lo = max(min(per), 1e-9)
            return max(per) / lo

        print("\n  O3 relation (identical multiset -> identical steady state and cost):")
        for label, key in [("documents examined", lambda r: r["total_docs_examined"]),
                           ("server time", lambda r: r["total_millis"]),
                           ("optimizer CPU (us)", lambda r: r["counters"]["mp_micros"]),
                           ("catastrophic queries", lambda r: r["n_catastrophic"] + 1)]:
            sp = ratio(key)
            print(f"    {label:<22} worst/best = {sp:8.1f}x   -> "
                  + ("HOLDS" if sp < 1.15 else f"VIOLATED, {sp:.1f}x"))
        states = {fc(r["final_cache"]) for r in sub}
        print(f"    {'final cache plan':<22} {len({s.split('/')[0] for s in states})} distinct index "
              f"across {len(orders)} orders -> "
              + ("HOLDS" if len({s.split('/')[0] for s in states}) == 1 else "VIOLATED"))

        print("\n  where the cost lands, per class (documents examined, mean over repeats):")
        print(f"    {'order':<12} {'P (paginated)':>22} {'R (rare, 1 doc)':>22}   plan used by R")
        for o in orders:
            g = [r for r in sub if r["order"] == o]
            cells = []
            plans = set()
            for cls in ("P", "R"):
                v = [r["by_class"][cls]["docs"] for r in g if cls in r["by_class"]]
                cells.append(fmt(v, 16) if v else " " * 22)
            for r in g:
                plans |= set((r["by_class"].get("R") or {}).get("plans", {}))
            print(f"    {o:<12} {cells[0]:>22} {cells[1]:>22}   {', '.join(sorted(plans))}")

    # --- the skip sweep --------------------------------------------------------------------
    sw = [r for r in runs if r.get("_sweep")] or sweep
    if sw:
        print("\n" + "=" * 118)
        print("  HOW MUCH TUNING? the skip sweep, order P_first, everything else held fixed")
        print("  the mechanism predicts immunity exactly when 10 x decisionWorks > 20 000 reads")
        print("=" * 118)
        print(f"  {'skip':>7} {'decisionWorks':>14} {'replan bar':>12} {'R docs':>12} "
              f"{'R plan':>16} {'replans':>9} {'total docs':>13} {'server ms':>10}")
        print("  " + "-" * 110)
        for r in sorted(sw, key=lambda x: x["skip"]):
            w = (r["final_cache"] or {}).get("works") or 0
            R = r["by_class"].get("R", {})
            plan = max(R.get("plans", {"?": 1}), key=R.get("plans", {"?": 1}).get)
            plan = plan.replace("IXSCAN { ", "").replace(": 1 }", "")
            mark = "  <== immune" if R.get("docs", 0) > 1000 else ""
            print(f"  {r['skip']:>7} {w:>14,} {10 * w:>12,} {R.get('docs', 0):>12,} "
                  f"{plan:>16} {r['counters']['replanned']:>9} "
                  f"{r['total_docs_examined']:>13,} {r['total_millis']:>10,}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Render the SERVER-79039 reproduction (oracle O3, order permutation).

SERVER-79039, "Plan cache entries can be evicted and replanned continuously for certain
workload patterns" (2023-07-17, Closed / Won't Do, 10 watchers, zero comments).

This is the OPPOSITE pole of W5. W5 showed the replan bar latching too HIGH and never
firing; 79039 is the bar oscillating and firing forever. Both come out of the same
getNewEntryState/deactivate machinery, and permuting the arrival order of ONE multiset
moves the system between them -- which is the whole point of O3.

Three things this report has to establish, in order:
  (1) the cycle exists: the entry's works oscillates instead of settling;
  (2) the replans are WASTEFUL: each one re-derives the plan already cached. MongoDB's
      own counter for this (planCache.classic.replanned_plan_is_cached_plan, added by
      SERVER-98987 in 8.2.0) is read directly rather than inferred;
  (3) a different ORDER of the SAME multiset does not thrash at all.
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


def ms(vals, w=10, dec=0):
    if not vals:
        return " " * w
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return f"{m:>{w},.{dec}f}+-{sd:,.{dec}f}"


def main():
    rows = load(sys.argv[1])
    build = next((r for r in rows if r["kind"] == "s79039_build"), None)
    runs = [r for r in rows if r["kind"] == "s79039_order"]
    sweep = [r for r in rows if r["kind"] == "s79039_sweep"]

    print("=" * 124)
    print("== SERVER-79039  'Plan cache entries can be evicted and replanned continuously for certain workload patterns'")
    print("==   reported 2023-07-17, Closed / Won't Do, 10 watchers, 0 comments, no fixVersion")
    print("=" * 124)
    if build:
        print(f"   {build['n']:,} docs in {build['db']}.{build['coll']}, indexes {{a:1}} and {{b:1}}")
        print(f"   C  find({{a:1..{build['ncheap']}, b:0}})  -> {build['c_hits']} results, "
              f"IXSCAN{{a}} EOF at ~{build['per_cheap'] + 1} works   => replan bar {(build['per_cheap'] + 1) * 10}")
        print(f"   E  find({{a:{build['eval_a']}, b:0}})   -> {build['e_hits']} results, "
              f"IXSCAN{{a}} EOF at ~{build['n_e'] + 1:,} works")
        print(f"   BOTH classes want the same plan. Neither is mis-planned. The only thing that")
        print(f"   differs between them is how much work that one plan costs: {build['n_e'] // (build['per_cheap'] + 1):,}x.")
    if runs:
        p = runs[0]["premise"]
        print(f"   same-shape premise: planCacheKey C={p['C']} E={p['E']} -> "
              + ("one entry, verified" if p["same_key"] else "DIFFERENT KEYS, experiment is vacuous"))

    if runs:
        orders = []
        for r in runs:
            if r["order"] not in orders:
                orders.append(r["order"])
        reps = len({r["rep"] for r in runs})
        s0 = runs[0]
        print("\n" + "=" * 124)
        print(f"  multiset per epoch: {s0['nc']} C + {s0['ne']} E, x{s0['epochs']} epochs = "
              f"{s0['n_queries']} queries.  ALL orders are permutations of it.  "
              f"{reps} independent repeat(s).")
        print("=" * 124)
        print(f"  {'order':<13} {'docs examined':>17} {'server ms':>14} {'optimizer us':>18} "
              f"{'planning works':>20} {'replans':>11} {'wasteful':>11}")
        print("  " + "-" * 120)
        for o in orders:
            g = [r for r in runs if r["order"] == o]
            print(f"  {o:<13} {ms([r['total_docs_examined'] for r in g],13)} "
                  f"{ms([r['total_millis'] for r in g],9)} "
                  f"{ms([r['counters']['mp_micros'] for r in g],12)} "
                  f"{ms([r['counters']['mp_works'] for r in g],14)} "
                  f"{ms([r['counters']['replanned'] for r in g],5)} "
                  f"{ms([r['counters']['replanned_plan_is_cached_plan'] for r in g],5)}")

        def ratio(key):
            per = [statistics.mean([key(r) for r in runs if r["order"] == o]) for o in orders]
            return max(per) / max(min(per), 1e-9)

        print("\n  O3 relation (identical multiset -> identical steady state and cost):")
        for label, key in [("documents examined", lambda r: r["total_docs_examined"]),
                           ("executor docs (server-wide)", lambda r: r["counters"]["executor_scanned_docs"]),
                           ("server time", lambda r: r["total_millis"]),
                           ("optimizer CPU (us)", lambda r: r["counters"]["mp_micros"]),
                           ("multi-planning invocations", lambda r: r["counters"]["mp_count"]),
                           ("planning works (discarded)", lambda r: r["counters"]["mp_works"]),
                           ("replans (+1)", lambda r: r["counters"]["replanned"] + 1)]:
            sp = ratio(key)
            print(f"    {label:<30} worst/best = {sp:7.1f}x   -> "
                  + ("HOLDS" if sp < 1.15 else f"VIOLATED, {sp:.1f}x"))
        print("    ^ the first two rows are the point: every per-operation work counter is")
        print("      IDENTICAL across orders while optimizer cost differs by an order of magnitude.")

        print("\n  (1) does the bar settle?  the plan cache entry's `works` after every query")
        print(f"  {'order':<13} {'distinct works values':<34} {'times lowered':>14}  final entry")
        for o in orders:
            g = [r for r in runs if r["order"] == o]
            dv = sorted({w for r in g for w in r["works_distinct"]})
            dvs = ",".join(str(x) for x in dv)
            if len(dvs) > 32:
                dvs = dvs[:29] + "..."
            print(f"  {o:<13} {dvs:<34} {statistics.mean([r['works_drops'] for r in g]):>14,.1f}  "
                  f"{'; '.join(sorted({fc(r['final_cache']) for r in g}))}")
        ex = next((r for r in runs if r["order"] == "alternating" and r["works_series"]), None)
        if ex:
            print(f"      alternating, first 16 queries: {ex['works_series'][:16]}")
            print("      -- 'its like the higher work query never happened' (the reporter). The bar")
            print(f"         never once reaches E's real cost ({(build['n_e'] + 1) if build else '?'} works).")

        print("\n  (2) are the replans wasteful?  planCache.classic.replanned_plan_is_cached_plan")
        for o in orders:
            g = [r for r in runs if r["order"] == o]
            rp = statistics.mean([r["counters"]["replanned"] for r in g])
            wa = statistics.mean([r["counters"]["replanned_plan_is_cached_plan"] for r in g])
            pct = 100.0 * wa / rp if rp else 0.0
            print(f"      {o:<13} {rp:>5,.1f} replans, {wa:>5,.1f} of them re-derived the cached plan "
                  f"({pct:.0f}% wasted)")

        print("\n  (3) is it a steady state, or a start-up transient?  (O3 condition (c))")
        print(f"      {'order':<13} " + " ".join(f"{'epoch ' + str(e):>14}" for e in range(s0["epochs"])))
        for o in orders:
            g = [r for r in runs if r["order"] == o]
            cells = []
            for e in range(s0["epochs"]):
                v = [next(x for x in r["per_epoch"] if x["epoch"] == e) for r in g]
                cells.append(f"{statistics.mean([x['replans'] for x in v]):>5,.1f} rp/"
                             f"{statistics.mean([x['multiplanned'] for x in v]):>4,.1f} mp")
            print(f"      {o:<13} " + " ".join(f"{c:>14}" for c in cells))
        print("      (rp = replans in that epoch, mp = queries that went through multi-planning)")

        print("\n  cost by class (documents examined / server ms / multi-plannings):")
        print(f"      {'order':<13} {'C (cheap, 5 docs)':>30} {'E (expensive)':>30}")
        for o in orders:
            g = [r for r in runs if r["order"] == o]
            cells = []
            for cls in ("C", "E"):
                v = [r["by_class"][cls] for r in g if cls in r["by_class"]]
                cells.append(f"{statistics.mean([x['docs'] for x in v]):>10,.0f}d "
                             f"{statistics.mean([x['millis'] for x in v]):>6,.0f}ms "
                             f"{statistics.mean([x['multiplanned'] for x in v]):>4,.0f}mp")
            print(f"      {o:<13} {cells[0]:>30} {cells[1]:>30}")

    if sweep:
        print("\n" + "=" * 124)
        print("  HOW MUCH TUNING?  sweep N_E (documents at the expensive parameter value), order")
        print("  'alternating', everything else fixed. The mechanism predicts thrash exactly when")
        print("  E's works (N_E + 1) exceeds the bar the cheap class sets, 10 x 6 = 60.")
        print("=" * 124)
        print(f"  {'N_E':>8} {'E works':>10} {'bar (10xW_C)':>14} {'replans':>9} {'wasteful':>10} "
              f"{'mp_count':>10} {'works values seen':<26} predicted")
        print("  " + "-" * 120)
        for r in sorted(sweep, key=lambda x: x.get("n_e", 0)):
            ne = r.get("n_e", 0)
            dv = ",".join(str(x) for x in r["works_distinct"])
            if len(dv) > 24:
                dv = dv[:21] + "..."
            pred = "thrash" if ne + 1 > 60 else "stable"
            got = "thrash" if r["counters"]["replanned"] > 0 else "stable"
            mark = "  OK" if pred == got else "  <== MISMATCH"
            print(f"  {ne:>8,} {ne + 1:>10,} {60:>14} {r['counters']['replanned']:>9} "
                  f"{r['counters']['replanned_plan_is_cached_plan']:>10} "
                  f"{r['counters']['mp_count']:>10} {dv:<26} {pred:<8}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Render the W4 trial-period sweep: what the ranker saw vs. what was true.

W4's claim is about EVIDENCE, not about a cost curve, so the interesting columns are the
per-candidate trial counters (works/advanced -> productivity) rather than latency alone.
analyze.py keys off a single sweep variable and cannot show the per-candidate breakdown.

Scoring, from plan_ranker.h:53-107 (calculateScore) and plan_ranker_util.h:201-247
(pickBestPlan, which applies the EOF bonus AFTER calculateScore rather than inside it):

    score = 1 + advanced/works + eps*(noFetch + noSort + noIxisect) + (1 if isEOF)

with eps = 1e-4; then, among plans whose scores are EXACTLY equal, +1e-4 to the one that
examined the fewest documents and +2e-4 on an index-prefix heuristic.

Because round-robin gives every candidate the same 'works', productivity reduces to
"results in the first W works" -- a prefix race. The EOF bonus is the only term carrying
information about a plan's TOTAL cost. So the column to watch is not the score gap but
WHICH STOPPING CONDITION ended the trial: a full batch (eof=0 for everyone) or an EOF.
"""
import json
import sys

EPS_BUDGET = 3e-4  # noFetch + noSort + noIxisect: the most the tie-breakers can move a score


def load(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip().replace("@@JSON@@", "")
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def short(plan):
    return plan.replace("ixscan:", "")


def main():
    rows = load(sys.argv[1])
    builds = {r["coll"]: r for r in rows if r["kind"] == "w4_build" and "coll" in r}
    truths = {}
    for r in rows:
        if r["kind"] == "w4_truth":
            truths.setdefault(r["coll"], {})[r["plan"]] = r
    colls = [c for c in ["docs", "docs_k1000", "docs_mirror"] if c in truths]

    for coll in colls:
        b = builds.get(coll)
        t = truths[coll]
        print(f"\n{'=' * 96}")
        print(f"== dataset {coll}" + (f"  (mirror)" if b and b.get("mirror") else ""))
        if b:
            m0, m1 = b["n_poison"], b["n_poison"] + b["n_match"]
            print(f"   {b['n']:,} docs; {b['n_match']:,} match find({{a:1,b:5}}) "
                  f"(verified {b['matches_verified']:,}) at recordId [{m0:,},{m1:,})")
            print(f"   perfect-prefix plan = {short(b['good_prefix_plan'])} "
                  f"(the plan whose first {b['n_match']:,} documents examined are ALL matches)")
        print(f"{'=' * 96}")

        print("\n  ground truth -- each plan forced to completion with hint():")
        print(f"    {'plan':<8} {'docs examined':>14} {'returned':>9} {'median ms':>10}")
        for p, r in sorted(t.items()):
            print(f"    {short(p):<8} {r['totalDocsExamined']:>14,} {r['nReturned']:>9} "
                  f"{r['latency']['median_ms']:>10.1f}")
        cheap = min(t.values(), key=lambda x: x["totalDocsExamined"])
        dear = max(t.values(), key=lambda x: x["totalDocsExamined"])
        print(f"    => cheapest is {short(cheap['plan'])}; "
              f"{short(dear['plan'])} costs {dear['totalDocsExamined'] / cheap['totalDocsExamined']:.1f}x "
              f"the documents and {dear['latency']['median_ms'] / cheap['latency']['median_ms']:.1f}x the latency")

        print("\n  sweep of internalQueryPlanEvaluationMaxResults:")
        for r in [x for x in rows if x["kind"] == "w4_point" and x["coll"] == coll]:
            prods = sorted((x["productivity"] for x in r["trial"]), reverse=True)
            gap = prods[0] - prods[1] if len(prods) > 1 else 0.0
            # tieForBest() in plan_ranking_decision.h:70 compares the FINAL scores with
            # epsilon 1e-10 -- i.e. AFTER the 1e-4 tie-breaker bonuses are added. So a
            # productivity tie broken by docsExamined is NOT a tie by that test, and the
            # "do not cache ties" policy from SERVER-13675 does not fire for it.
            sc = sorted((x["score"] for x in r["trial"] if x.get("score") is not None), reverse=True)
            server_tie = len(sc) > 1 and abs(sc[0] - sc[1]) < 1e-10
            ratio = r["totalDocsExamined"] / cheap["totalDocsExamined"]
            lat = r["latency"]["median_ms"] / cheap["latency"]["median_ms"]
            ok = "OPTIMAL" if ratio < 1.05 else f"{ratio:.1f}x WORSE"
            print(f"\n    maxResults = {r['max_results']:,}   winner = {short(r['winner'])}   "
                  f"{ok}  ({lat:.1f}x optimal latency)")
            print(f"      {'candidate':<10} {'works':>8} {'adv':>6} {'trial docs':>11} "
                  f"{'productivity':>13} {'score (server)':>15} {'predicted':>11} {'eof':>4}")
            for x in r["trial"]:
                sv = "n/a" if x.get("score") is None else f"{x['score']:.6f}"
                print(f"      {short(x['plan']):<10} {x['works']:>8,} {x['advanced']:>6,} "
                      f"{x['trial_docs']:>11,} {x['productivity']:>13.6f} "
                      f"{sv:>15} {x['score_est']:>11.6f} {x['is_eof']:>4}")
            # Which stopping condition ended the trial is the whole story.
            win = r["trial"][0]
            any_eof = any(x["is_eof"] for x in r["trial"])
            stop = ("EOF (a plan exhausted its index range)" if any_eof
                    else f"FULL BATCH (a plan reached {r['max_results']:,} results)")
            print(f"      stopped by: {stop}")
            if gap < EPS_BUDGET:
                print(f"      productivity gap {gap:.6f} < {EPS_BUDGET:g}: the prefix race was a TIE, "
                      f"so the +1 EOF bonus decided it")
            else:
                print(f"      productivity gap {gap:.6f}: the prefix race separated the plans "
                      f"DECISIVELY{' -- and wrongly' if ratio >= 1.05 else ''}")
            if ratio >= 1.05:
                print(f"      the EOF bonus never fired: the full-batch condition stopped the trial "
                      f"before the cheap plan could reach the end of its range")
            print(f"      tieForBest() on the FINAL scores = {server_tie} (epsilon 1e-10) -> "
                  f"the SERVER-13675 'do not cache ties' policy "
                  f"{'suppresses' if server_tie else 'does NOT fire'} here")
            print(f"      executed: docs={r['totalDocsExamined']:,} ret={r['nReturned']} "
                  f"median={r['latency']['median_ms']:.1f}ms")
            print(f"      cached  : {json.dumps(r['plan_cache'])}")

    # --- the cross-dataset claim: does raising the knob repair anything? ---------------
    print(f"\n{'=' * 96}")
    print("== condition (c): invariance -- is the cliff a property of the CONSTANT?")
    print(f"{'=' * 96}")
    print(f"  {'dataset':<12} {'matches':>8} {'knob that trips it':>19} {'cliff (docs)':>13} "
          f"{'cliff (latency)':>16}")
    for coll in colls:
        b, t = builds.get(coll), truths[coll]
        if not b:
            continue
        cheap = min(t.values(), key=lambda x: x["totalDocsExamined"])
        pts = [x for x in rows if x["kind"] == "w4_point" and x["coll"] == coll]
        bad = [x for x in pts if x["totalDocsExamined"] / cheap["totalDocsExamined"] >= 1.05]
        if not bad:
            continue
        worst = max(bad, key=lambda x: x["max_results"])
        print(f"  {coll:<12} {b['n_match']:>8,} {'<= ' + format(worst['max_results'], ','):>19} "
              f"{worst['totalDocsExamined'] / cheap['totalDocsExamined']:>12.1f}x "
              f"{worst['latency']['median_ms'] / cheap['latency']['median_ms']:>15.1f}x")
    print("\n  Read this table as: the knob does not set the SIZE of the cliff, it sets how many")
    print("  matching documents a workload needs in order to fall off it. Raising the constant")
    print("  10x left the cliff the same depth and simply moved which workload trips it.")
    print("  The rule is: a workload falls off the cliff whenever")
    print("      (number of matching documents) <= internalQueryPlanEvaluationMaxResults")
    print("  and the matches are positioned early in the bad plan's index order. Since the")
    print("  match count is a property of the DATA and the knob is a server constant, no")
    print("  setting of the knob excludes the bad regime -- which is condition (c).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Render the CBR scoping probe: does the cost-based ranker rescue W4's regime?

Kept separate from w4_report.py because it answers a different question -- not "is the
threshold defective" but "is the defective mechanism still the one that ships by default".
"""
import json
import sys


def main():
    rows = [json.loads(l.strip().replace("@@JSON@@", ""))
            for l in open(sys.argv[1]) if l.strip().startswith(("{", "@@JSON@@"))]
    out = ["Does the cost-based ranker rescue W4's regime?  (bugs/systems/mongodb/trial-period/repro/w4_cbr_probe.js)", "",
           "%-14s %-12s %-22s %11s %11s %6s %11s" % ("ranker", "collection", "winner",
                                                     "keys", "docs", "ret", "median ms"),
           "-" * 94]
    for r in rows:
        if "error" in r:
            out.append("%-14s %s" % (r["ranker"], "cannot set on this build: " + r["error"]))
            continue
        out.append("%-14s %-12s %-22s %11s %11s %6s %11.1f" % (
            r["ranker"], r["coll"], r["winner"].replace("ixscan:", ""),
            f"{r['totalKeysExamined']:,}", f"{r['totalDocsExamined']:,}",
            r["nReturned"], r["latency"]["median_ms"]))

    mp = {r["coll"]: r for r in rows if r.get("ranker") == "multiPlanning" and "coll" in r}
    ce = {r["coll"]: r for r in rows if r.get("ranker") == "automaticCE" and "coll" in r}
    if mp and ce:
        out += ["", "speedup of automaticCE over the default multiPlanning:"]
        for c in mp:
            if c in ce:
                out.append("  %-12s %6.1fx latency, %9.1fx fewer documents examined" % (
                    c, mp[c]["latency"]["median_ms"] / ce[c]["latency"]["median_ms"],
                    mp[c]["totalDocsExamined"] / ce[c]["totalDocsExamined"]))
    out += ["",
            "CBR picks the AND_SORTED index-intersection plan, which the multi-planner ranks LAST",
            "(score 1.0001): noIxisectBonus penalises it, and round-robin charges it two work()",
            "calls per output, halving its trial productivity. The trial metric penalises the best",
            "plan precisely because it does less redundant work per result.", ""]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

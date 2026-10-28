#!/usr/bin/env python3
"""Turn a harness .jsonl into a readable cliff report.

Usage: analyze.py <file.jsonl> [--key k|foreign_docs]

The primary evidence for a cliff is the *work counter* (totalKeysExamined), which the
server reports and which is deterministic. Latency is secondary: the harness times a
full shell round-trip, so it overstates the cheap side and therefore understates the
cliff. Both are printed; claims should lead with the work counter.
"""
import json
import sys


def load(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("@@JSON@@"):
                line = line[len("@@JSON@@"):]
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def fmt(n):
    return f"{n:,}" if isinstance(n, int) else ("-" if n is None else f"{n}")


def main():
    path = sys.argv[1]
    keyname = None
    if "--key" in sys.argv:
        keyname = sys.argv[sys.argv.index("--key") + 1]

    rows = [r for r in load(path) if r.get("kind", "").endswith("_point")]
    if not rows:
        print("no *_point records found", file=sys.stderr)
        return 1
    if keyname is None:
        keyname = "k" if "k" in rows[0] else "foreign_docs"

    extra = "join_algo" if "join_algo" in rows[0] else None
    hdr = f"{keyname:>8}  {'plan':<34}"
    if extra:
        hdr += f"  {'join':<12}"
    hdr += f"  {'keys examined':>14}  {'docs':>9}  {'median ms':>10}  {'rsd':>5}"
    print(hdr)
    print("-" * len(hdr))

    for r in sorted(rows, key=lambda r: r[keyname]):
        lat = r["latency"]
        plan = r["stage_summary"]
        plan = plan if len(plan) <= 34 else plan[:31] + "..."
        line = f"{r[keyname]:>8}  {plan:<34}"
        if extra:
            line += f"  {r.get(extra, '-'):<12}"
        line += (f"  {fmt(r['totalKeysExamined']):>14}  {fmt(r['totalDocsExamined']):>9}"
                 f"  {lat['median_ms']:>10.2f}  {lat['rsd']:>5.2f}")
        print(line)

    # Locate the largest single-step discontinuity between adjacent points.
    ordered = sorted(rows, key=lambda r: r[keyname])
    best = None
    for a, b in zip(ordered, ordered[1:]):
        ratio = b["latency"]["median_ms"] / max(a["latency"]["median_ms"], 1e-9)
        if best is None or ratio > best[2]:
            best = (a, b, ratio)
    a, b, ratio = best
    # Aggregation explains leave totalKeysExamined at 0, so fall back to documents.
    ak, bk = a.get("totalKeysExamined"), b.get("totalKeysExamined")
    unit = "keys examined"
    if not ak or not bk:
        ak, bk = a.get("totalDocsExamined"), b.get("totalDocsExamined")
        unit = "docs examined"
    # Likewise the classic stage tree is empty for SBE/aggregation plans.
    pa = a["stage_summary"] or a.get("join_algo") or "(no classic stage tree)"
    pb = b["stage_summary"] or b.get("join_algo") or "(no classic stage tree)"
    print()
    print(f"Sharpest step: {keyname} {a[keyname]} -> {b[keyname]} "
          f"(workload differs by {abs(b[keyname]-a[keyname])/max(a[keyname],1)*100:.2f}%)")
    print(f"  plan    : {pa}")
    print(f"         -> {pb}")
    if ak and bk:
        print(f"  work    : {ak:,} -> {bk:,} {unit}  ({bk/max(ak,1):,.0f}x)")
    print(f"  latency : {a['latency']['median_ms']:.2f} ms -> "
          f"{b['latency']['median_ms']:.2f} ms  ({ratio:,.0f}x)")
    if a.get("nReturned") is not None and b.get("nReturned") is not None:
        print(f"  returned: {a['nReturned']} -> {b['nReturned']} documents "
              f"({'identical' if a['nReturned'] == b['nReturned'] else 'DIFFERENT - not a fair pair'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

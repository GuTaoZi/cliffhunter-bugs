#!/usr/bin/env python3
"""Inclusive share of server samples under each function of interest, per arm (mean over repetitions), from the
folded stacks in OUT (profile.sh's output directory), and the heaviest full stack through each symptom function in the slow arm.

    python3 tools/probes/mongo_profile/shares.py OUT > OUT/shares.md
"""
import collections
import glob
import os
import re
import sys

O = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
# (label, regex on a frame). Names from the source map at 6d990baca59c.
FUNCS = [
    ("multi-planning: MultiPlanStage::runTrials", r"MultiPlanStage::runTrials"),
    ("  candidate trials: MultiPlanStage::workAllPlans", r"MultiPlanStage::workAllPlans"),
    ("  ranking: MultiPlanStage::pickBestPlan", r"MultiPlanStage::pickBestPlan"),
    ("  plan cache write: PlanCacheBase<...>::set", r"PlanCacheBase<.*>::set\b|plan_cache_util::.*PlanCacheWriter"),
    ("query planning: QueryPlanner::plan", r"QueryPlanner::plan\("),
    ("plan from cache: QueryPlanner::planFromCache", r"QueryPlanner::planFromCache"),
    ("cached-plan trial: CachedPlanStage::pickBestPlan", r"CachedPlanStage::pickBestPlan"),
    ("SBE cached-plan trial: executeCachedCandidateTrial", r"executeCachedCandidateTrial"),
    ("replan: CachedPlanStage::replan", r"CachedPlanStage::replan"),
    ("plan ranking (CBR then multi-planning): PlanRanker::rankPlans", r"plan_ranking::PlanRanker::rankPlans"),
    ("SBE plan build: buildSlotBasedExecutableTree", r"buildSlotBasedExecutableTree"),
    ("classic plan build: buildClassicExecutableTree", r"buildClassicExecutableTree"),
    ("execution: getNextBatch", r"getNextBatch"),
    ("classic IndexScan::doWork", r"mongo::IndexScan::doWork"),
    ("classic FetchStage::doWork", r"mongo::FetchStage::doWork"),
    ("SBE FetchStage::getNext", r"sbe::FetchStage::getNext"),
    ("SBE index scan getNext", r"sbe::IndexScanStageBaseImpl<.*>::getNext|sbe::SimpleIndexScanStage"),
    ("exception unwinding: _Unwind_RaiseException", r"_Unwind_RaiseException|__cxa_throw"),
]
# The function that dominates each arm: re-planning, or running the plan taken from the cache.
MAIN = {("s79039", "alternating"): r"MultiPlanStage::runTrials", ("s79039", "blocked_EC"): r"CachedPlanStage::pickBestPlan",
        ("s107471", "P_first"): r"CachedPlanStage::pickBestPlan", ("s107471", "R_first"): r"MultiPlanStage::runTrials"}


def load(path):
    st = collections.Counter()
    for line in open(path):
        k, _, n = line.rstrip("\n").rpartition(" ")
        st[k] += int(n)
    return st


def share(st, rx):
    r = re.compile(rx)
    tot = sum(st.values())
    return sum(n for k, n in st.items() if any(r.search(f) for f in k.split(";"))) / tot if tot else 0.0


def main():
    runs = collections.defaultdict(list)
    for p in sorted(glob.glob(f"{O}/*.folded")):
        bug, arm, rep = re.match(r"(s\d+)-(.+)-r(\d+)\.folded", os.path.basename(p)).groups()
        runs[(bug, arm)].append(load(p))
    out = ["# Where the server's CPU goes, slow vs fast arrival order (perf, 499 Hz, frame-pointer call graphs)", "",
           "Inclusive share of all samples of the mongod process whose stack passes through the function; mean of "
           "the repetitions. A sample counts once per row even if the function recurs.", ""]
    for bug, (slow, fast) in (("s79039", ("alternating", "blocked_EC")), ("s107471", ("P_first", "R_first"))):
        a, b = runs[(bug, slow)], runs[(bug, fast)]
        ns, nf = [sum(s.values()) for s in a], [sum(s.values()) for s in b]
        out += [f"## {bug}: {slow} (slow) vs {fast} (fast)", "",
                f"samples per run: {slow} {ns}, {fast} {nf}", "",
                f"| function | {slow} | {fast} | samples {slow} / {fast} |", "|---|---|---|---|"]
        for label, rx in FUNCS:
            sa = sum(share(s, rx) for s in a) / len(a)
            sb = sum(share(s, rx) for s in b) / len(b)
            ca = sum(share(s, rx) * sum(s.values()) for s in a) / len(a)
            cb = sum(share(s, rx) * sum(s.values()) for s in b) / len(b)
            ratio = f"{ca / cb:.1f}x" if cb else ("-" if not ca else "only slow")
            if sa < 0.005 and sb < 0.005:
                continue
            out.append(f"| {label} | {100 * sa:.1f}% | {100 * sb:.1f}% | {ratio} |")
        for arm_name, arm_runs in ((slow, a), (fast, b)):
            rx = MAIN[(bug, arm_name)]
            r = re.compile(rx)
            merged = collections.Counter()
            for s in arm_runs:
                for k, n in s.items():
                    fr = k.split(";")
                    idx = next((i for i, f in enumerate(fr) if r.search(f)), None)
                    if idx is not None:
                        merged[";".join(fr[1:idx + 1])] += n
            if not merged:
                continue
            k, n = merged.most_common(1)[0]
            tot = sum(sum(s.values()) for s in arm_runs)
            leaves = collections.Counter()
            for s in arm_runs:
                for kk, nn in s.items():
                    fr = kk.split(";")
                    if any(r.search(f) for f in fr):
                        leaves[fr[-1]] += nn
            under = sum(leaves.values())
            out += ["", f"Heaviest stack down to `{rx}` in {arm_name} ({100 * n / tot:.1f}% of samples; outermost first, "
                    "the transport and future frames above handleRequest left out):", "", "```"]
            fr = k.split(";")
            start = next((i for i, f in enumerate(fr) if "handleRequest" in f), 0)
            out += [f"  {re.sub(r'[(][^()]*[)]$', '()', f)[:160]}" for f in fr[start:]] + ["```", "",
                    f"Hottest functions (self samples) under it, share of its {under} samples:", ""]
            out += [f"- {100 * nn / under:.1f}% `{re.sub(r'[(].*$', '', f)[:140]}`" for f, nn in leaves.most_common(10)]
        out.append("")
    print("\n".join(out))


if __name__ == "__main__":
    main()

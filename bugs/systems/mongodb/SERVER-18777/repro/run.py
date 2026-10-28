#!/usr/bin/env python3
"""SERVER-18777 (queue rank 31): a rooted $or's branch plans are cached with no trial, so a plan cached for one
parameter class is used for the other, however bad, and never replanned.

MongoDB 8.2.12 (the release binary on PATH), one mongod in a systemd user unit (tools/harness/start_mongod_cgroup.sh)
so that its CPU (cpu.stat usage_usec) and peak memory (memory.peak, reset before each pass) are the server's alone.
Data: s18777_build.js (300,000 documents; class A = {a: i, b: 0} is 20 documents under IXSCAN{a} and 280,000 under
IXSCAN{b}, class B the mirror). Passes: s18777_order.js, which runs six arrival orders of A and B queries for one arm:
  orjoin  find({$or: [{a: X, b: Y}, {c: K}]}), the default (branches subplanned and cached per branch: the bug)
  whole   the same query with internalQueryPlanOrChildrenIndependently=false (the whole $or cached, with the trial)
  plain   the branch alone, find({a: X, b: Y}) (a cached plan with the trial and replanning)
Each arm runs a traced pass (profiler and $planCacheStats: docs examined, plan, cache state per query) and a quiet
pass (latency only). REPS repetitions, the arm order rotated per repetition.

    run.py measure [REPS] | report
"""
import json
import os
import statistics as st
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
H = f"{REPO}/tools/harness"
PORT, UNIT = 15452, "mongod-s18777"
DATA_ROOT = f"{ROOT}/mongo-s18777"
ARMS = ["orjoin", "whole", "plain"]
ENV = dict(os.environ, CH_PORT=str(PORT), CH_UNIT=UNIT, CH_DATA_ROOT=DATA_ROOT, CH_CACHE_GB="4",
           CH_LIB=f"{H}/lib.js")


def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)


def cgroup():
    cg = sh("systemctl", "--user", "show", "-p", "ControlGroup", "--value", f"{UNIT}.service").stdout.strip()
    return f"/sys/fs/cgroup{cg}"


def cpu_us(cg):
    for line in open(f"{cg}/cpu.stat"):
        if line.startswith("usage_usec"):
            return int(line.split()[1])


def mongosh(script, env):
    r = sh("mongosh", "--quiet", "--port", str(PORT), "--file", script, env=env, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:] + r.stdout[-2000:])
    return r.stdout


def passes(rep, arm, quiet, cg, out):
    try:
        open(f"{cg}/memory.peak", "w").write("0")
        peak_reset = True
    except OSError:
        peak_reset = False
    c0, t0 = cpu_us(cg), time.time()
    txt = mongosh(f"{D}/s18777_order.js", dict(ENV, S3_ARM=arm, S3_QUIET=str(quiet), S3_REP=str(rep)))
    wall, c1 = time.time() - t0, cpu_us(cg)
    peak = int(open(f"{cg}/memory.peak").read())
    for line in txt.splitlines():
        if line.startswith("@@JSON@@"):
            rec = json.loads(line[8:])
            rec.update({"pass_wall_s": round(wall, 2), "pass_server_cpu_s": round((c1 - c0) / 1e6, 3),
                        "pass_server_peak_mb": round(peak / 2**20, 1), "peak_reset": peak_reset})
            out.write(json.dumps(rec) + "\n")
    out.flush()
    print(f"rep {rep} {arm} quiet={quiet}: {wall:.1f} s, server cpu {(c1 - c0) / 1e6:.2f} s, peak "
          f"{peak / 2**20:.0f} MB", flush=True)
    for line in txt.splitlines():
        if not line.startswith("@@JSON@@"):
            print("   ", line, flush=True)


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    os.makedirs(f"{D}/logs", exist_ok=True)
    r = sh("sh", f"{H}/start_mongod_cgroup.sh", env=ENV)
    if r.returncode != 0:
        raise RuntimeError(r.stderr + r.stdout)
    try:
        cg = cgroup()
        info = json.loads(sh("mongosh", "--quiet", "--port", str(PORT), "--eval",
                             "JSON.stringify(db.adminCommand({buildInfo:1}))").stdout)
        json.dump({"version": info.get("version"), "gitVersion": info.get("gitVersion"),
                   "debug": info.get("debug"), "allocator": info.get("allocator"),
                   "buildEnvironment": info.get("buildEnvironment", {}).get("ccflags")},
                  open(f"{D}/data/buildinfo.json", "w"))
        b = mongosh(f"{D}/s18777_build.js", ENV)
        open(f"{D}/logs/build.log", "w").write(b)
        with open(f"{D}/data/runs.jsonl", "a") as out:
            for rep in range(1, reps + 1):
                order = ARMS[rep - 1:] + ARMS[:rep - 1]
                for arm in order:
                    for quiet in (0, 1):
                        passes(rep, arm, quiet, cg, out)
    finally:
        sh("systemctl", "--user", "stop", f"{UNIT}.service")


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl") if '"s18777_order"' in l]
    orders = []
    for r in rows:
        if r["order"] not in orders:
            orders.append(r["order"])
    out = ["# SERVER-18777: rooted $or branches cached without a trial (MongoDB 8.2.12)", "",
           "Six arrival orders of class A and class B queries per arm. Latency: the quiet passes (no profiler), "
           "per-class median and maximum wall time per query (ms), mean over repetitions; slow: queries that examined "
           "more than 100,000 documents (traced passes). Server CPU and peak memory: per pass, from the mongod "
           "unit's cgroup.", "",
           "| order | arm | A median ms | A max ms | B median ms | B max ms | slow A | slow B | multiplans | replans |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for o in orders:
        for arm in ARMS:
            q = [r for r in rows if r["order"] == o and r["arm"] == arm and r["quiet"]]
            t = [r for r in rows if r["order"] == o and r["arm"] == arm and not r["quiet"]]
            if not q:
                continue

            def m(rs, cls, k):
                v = [r["by_class"][cls][k] for r in rs if cls in r["by_class"] and r["by_class"][cls][k] is not None]
                return f"{st.mean(v):.1f}" if v else "-"
            out.append(f"| {o} | {arm} | {m(q, 'A', 'wall_ms_median')} | {m(q, 'A', 'wall_ms_max')} | "
                       f"{m(q, 'B', 'wall_ms_median')} | {m(q, 'B', 'wall_ms_max')} | {m(t, 'A', 'slow')} | "
                       f"{m(t, 'B', 'slow')} | {st.mean(r['counters']['mp_count'] for r in t):.1f} | "
                       f"{st.mean(r['counters']['replanned'] for r in t):.1f} |")
    out += ["", "| arm | passes | server CPU s per pass (quiet) | server peak MB (quiet) | queries' wall s per pass "
            "(quiet) |", "|---|---|---|---|---|"]
    for arm in ARMS:
        q = {}
        for r in rows:
            if r["arm"] == arm and r["quiet"]:
                q.setdefault((r["rep"]), r)
        v = list(q.values())
        if v:
            wsum = [sum(x["wall_ms_sum"] for x in rows if x["arm"] == arm and x["quiet"] and x["rep"] == r["rep"]) / 1e3
                    for r in v]
            out.append(f"| {arm} | {len(v)} | {st.mean(r['pass_server_cpu_s'] for r in v):.2f} | "
                       f"{st.mean(r['pass_server_peak_mb'] for r in v):.0f} | {st.mean(wsum):.2f} |")
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 3), "report": report}[sys.argv[1]]()

#!/usr/bin/env python3
"""A one-parameter sweep across a planner threshold: MongoDB's explode-for-sort (main branch item W1), on our own
release build of 6d990ba (tools/mongo/mongo_build.sh; -O2, checked from buildInfo).

The planner turns `find({a: {$in: [...]}}).sort({b: 1})` on an index {a: 1, b: 1} into one index scan per $in value
merged in b order (SORT_MERGE: a limit stops it after a few keys) while the number of scans is at most
internalQueryMaxScansToExplode (200, src/mongo/db/query/planner_analysis.cpp:1365-1376 at 6d990ba); above it, into one
scan of every matching key and a blocking sort. The sweep varies the $in length N around 200 and records, per point,
explain's keys and documents examined and the winning plan's stages, then the wall latency of the query (median of
5), the server's CPU over those 5 and its peak RSS. Points run interleaved, REPS times, in a shuffled order each
time. No probes and no rebuild: the cliff is found from outside.

    bugs/systems/mongodb/explode-for-sort/repro/run.py [--docs=1000000] [--reps=3] [--port=15450]
Writes raw/runs.jsonl and summary.json here.
"""
import json
import os
import random
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "probes"))
import mongowire  # noqa: E402

D = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
# The mongod to sweep (default: our release build of 6d990ba) and the directory of its C++ runtime, if it needs one.
MONGOD = os.environ.get("MONGOD") or os.path.join(D, "build/mongo-6d990baca59c/src/bazel-bin/src/mongo/db/mongod")
_NIX_GCC = "/nix/store/sb414m3xc7hq2pa6arvx6imwlywm7vy3-gcc-14.4.0-lib/lib"
GCC_LIB = os.environ.get("MONGOD_LIBS", _NIX_GCC if os.path.isdir(_NIX_GCC) else "")
POINTS = [100, 150, 190, 199, 200, 201, 202, 210, 250]
KEYS_A = 250                       # distinct values of a; every $in value up to 250 matches documents


def proc_cpu(pid):
    st = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(st[11]) + int(st[12])) / os.sysconf("SC_CLK_TCK")


def proc_hwm(pid):
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmHWM"):
            return int(l.split()[1]) / 1024.0
    return None


def stages(plan):
    out = [plan.get("stage")]
    for k in ("inputStage", "inputStages"):
        v = plan.get(k)
        for p in (v if isinstance(v, list) else [v] if v else []):
            out += stages(p)
    return out


def main():
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    ndocs, reps, port = int(opts.get("docs", 1000000)), int(opts.get("reps", 3)), int(opts.get("port", 15450))
    run = os.path.join(D, "mongo", "run", "explode-for-sort")
    os.makedirs(os.path.join(run, "db"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "data", "experiments", "mongo-explode-for-sort", "raw"), exist_ok=True)
    srv = subprocess.Popen([MONGOD, "--port", str(port), "--bind_ip", "127.0.0.1", "--dbpath", os.path.join(run, "db"),
                            "--unixSocketPrefix", run, "--logpath", os.path.join(run, "mongod.log"),
                            "--wiredTigerCacheSizeGB", "2"],
                           env=dict(os.environ, **({"LD_LIBRARY_PATH": GCC_LIB} if GCC_LIB else {})),
                           stdout=open(os.path.join(run, "stdout.txt"), "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(300):
            try:
                c = mongowire.Mongo(port, timeout=600)
                c.cmd({"ping": 1})
                break
            except OSError:
                time.sleep(0.1)
        bi = c.cmd({"buildInfo": 1})
        flags = [f for f in bi["buildEnvironment"]["cxxflags"].split() if f.startswith(("-O", "-DNDEBUG"))]
        c.cmd({"drop": "t"}, db="w", check=False)
        t0 = time.time()
        for s in range(0, ndocs, 10000):
            c.cmd({"insert": "t", "ordered": False,
                   "documents": [{"_id": i, "a": i % KEYS_A, "b": i} for i in range(s, min(s + 10000, ndocs))]}, db="w")
        c.cmd({"createIndexes": "t", "indexes": [{"key": {"a": 1, "b": 1}, "name": "a_b"}]}, db="w")
        load_s = time.time() - t0
        print(f"mongod {bi['version']} {' '.join(flags)}; {ndocs} documents and index in {load_s:.1f} s", flush=True)
        rows = []
        rnd = random.Random(1)
        out = open(os.path.join(REPO, "data", "experiments", "mongo-explode-for-sort", "raw", "runs.jsonl"), "w")
        for rep in range(reps):
            order = POINTS[:]
            rnd.shuffle(order)
            for n in order:
                q = {"find": "t", "filter": {"a": {"$in": list(range(n))}}, "sort": {"b": 1}, "limit": 10}
                ex = c.cmd({"explain": q, "verbosity": "executionStats"}, db="w")
                es = ex["executionStats"]
                plan = ex["queryPlanner"]["winningPlan"]
                lat = []
                cpu0 = proc_cpu(srv.pid)
                for _ in range(5):
                    t1 = time.time()
                    c.cmd(dict(q, batchSize=10), db="w")
                    lat.append((time.time() - t1) * 1000)
                r = {"rep": rep, "n": n, "keys": es["totalKeysExamined"], "docs": es["totalDocsExamined"],
                     "explain_ms": es["executionTimeMillis"], "plan": sorted(set(stages(plan.get("queryPlan", plan)))),
                     "latency_ms": round(statistics.median(lat), 2), "server_cpu_s_5q": round(proc_cpu(srv.pid) - cpu0, 3),
                     "peak_rss_mb": round(proc_hwm(srv.pid), 1)}
                rows.append(r)
                out.write(json.dumps(r) + "\n")
                out.flush()
                print(f"rep {rep} n {n:4}: keys {r['keys']:>9,} docs {r['docs']:>6} latency {r['latency_ms']:9.2f} ms "
                      f"cpu {r['server_cpu_s_5q']:.2f} s plan {'+'.join(r['plan'])}", flush=True)
        summary = {"mongod": bi["version"], "flags": flags, "documents": ndocs, "load_s": round(load_s, 1), "points": {}}
        for n in POINTS:
            rs = [r for r in rows if r["n"] == n]
            summary["points"][n] = {"keys": sorted({r["keys"] for r in rs}), "plan": rs[0]["plan"],
                                    "latency_ms_median": round(statistics.median(r["latency_ms"] for r in rs), 2),
                                    "latency_ms_range": [min(r["latency_ms"] for r in rs), max(r["latency_ms"] for r in rs)],
                                    "server_cpu_s_5q_median": round(statistics.median(r["server_cpu_s_5q"] for r in rs), 3)}
        summary["peak_rss_mb"] = max(r["peak_rss_mb"] for r in rows)
        json.dump(summary, open(os.path.join(REPO, "experiments", "cliffs", "mongo-explode-for-sort", "summary.json"), "w"), indent=1)
        print(json.dumps(summary["points"], indent=0))
    finally:
        try:
            c.cmd({"shutdown": 1, "force": True})
        except Exception:
            pass
        try:
            srv.wait(60)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    main()

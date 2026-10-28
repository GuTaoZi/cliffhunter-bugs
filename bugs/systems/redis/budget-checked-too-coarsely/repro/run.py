#!/usr/bin/env python3
"""redis/budget-checked-too-coarsely (queue rank 33): active defrag checks its time budget only between keys.

Bug (src/defrag.c at df45fed050d6): a list of more than active-defrag-max-scan-fields (1000) quicklist nodes is
deferred (defragLater, lines 512-524) and then defragged by scanLaterList (443-449), which walks every node in one
go (activeDefragQuickListNodes, 411-433, no time check; "list has no scan, we must finish it in one go", 902-904);
defragLaterStep checks ustime() > endtime only after the whole key (959-975). The cycle's budget (1071-1073,
1e6*cycle%/hz/100 us) is never consulted inside the list, so the main thread stalls for the whole list. Fixed
upstream in 485425cec76e (2020-02-18): scanLaterList checks the time every 128 nodes and resumes from a quicklist
bookmark next cycle. Parent df45fed050d6.

One run (fresh server per run, release builds with the bundled jemalloc), the fix's own test recipe
(tests/unit/memefficiency.tcl) at a larger size:
  1. list-max-ziplist-size 5; two lists filled alternately with 100-byte values (Lua batches), N items each, so
     their nodes interleave in the same slabs; DEL one list: about half of every slab is free (frag >= 1.7);
  2. measured: a 1 ms PING probe (tools/reproduce/pingprobe.py) on its own core; 3 s of baseline; CONFIG SET
     activedefrag yes; the window ends 2 s after active_defrag_running returns to 0 (at most 120 s); server CPU,
     main-thread CPU and peak RSS over the window; LATENCY HISTORY active-defrag-cycle (cycles over 1 ms).
Defrag settings: hz 100, cycle 25% min and max, so the per-cycle budget is 2,500 us. Arms alternate per repetition.

    run.py build | measure [REPS] | report
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
sys.path.insert(0, f"{REPO}/tools/reproduce")
from measure import Sampler  # noqa: E402
from pingprobe import Probe, reset_hwm, thread_cpu_s  # noqa: E402
from respclient import Resp, start, stop  # noqa: E402

ARMS = {"parent": "df45fed050d6", "fix": "485425cec76e"}
PORT = 15443
N = int(os.environ.get("N", 2_500_000))
SERVER_CPU, PROBE_CPU = 2, 4
ARGS = ["--hz", "100", "--list-max-ziplist-size", "5", "--active-defrag-max-scan-fields", "1000",
        "--active-defrag-threshold-lower", "10", "--active-defrag-ignore-bytes", "10mb",
        "--active-defrag-cycle-min", "25", "--active-defrag-cycle-max", "25", "--latency-monitor-threshold", "1",
        "--maxmemory", "0"]


def server(arm):
    return f"{ROOT}/build/redis-{ARMS[arm]}/src/src/redis-server"


def build():
    for arm, sha in ARMS.items():
        r = subprocess.run(["sh", f"{REPO}/tools/reproduce/build.sh", "redis", sha], capture_output=True, text=True)
        print(arm, sha, "rc", r.returncode, r.stdout.strip().split("\n")[-1][:120])


def ok(v):
    if isinstance(v, Exception):
        raise v
    return v


def pin(pid, cpu):
    for t in os.listdir(f"/proc/{pid}/task"):
        os.sched_setaffinity(int(t), {cpu})


def one(arm, rep):
    log = open(f"{D}/logs/{arm}-r{rep}.log", "w")
    p = start(server(arm), PORT, ARGS + ["--dir", f"{D}/logs"], log)
    try:
        pin(p.pid, SERVER_CPU)
        r = Resp(PORT, timeout=600)
        t0 = time.time()
        script = ("local v=string.rep('A',100) for i=1,tonumber(ARGV[1]) do redis.call('RPUSH',KEYS[1],v) "
                  "redis.call('RPUSH',KEYS[2],v) end return 1")
        for lo in range(0, N, 100_000):
            ok(r.cmd("EVAL", script, "2", "biglist1", "biglist2", str(min(N, lo + 100_000) - lo)))
        load_s = time.time() - t0
        dbg = ok(r.cmd("DEBUG", "OBJECT", "biglist1")).decode()
        ok(r.cmd("DEL", "biglist2"))
        time.sleep(0.5)
        m0 = r.info("memory")
        frag0 = float(m0.get("allocator_frag_ratio", 0))
        reset_hwm(p.pid)
        smp = Sampler(p.pid)
        smp.poll()
        smp.start()
        main0 = thread_cpu_s(p.pid)
        pr = Probe(PORT, 0.001, PROBE_CPU)
        pr.start()
        time.sleep(3.0)
        ctl = Resp(PORT, timeout=600)
        t_on = time.time()
        ok(ctl.cmd("CONFIG", "SET", "activedefrag", "yes"))
        ran, idle_since, trace = False, None, []
        while time.time() - t_on < 120:
            time.sleep(0.1)
            m = ctl.info("memory")
            running = int(m.get("active_defrag_running", 0))
            trace.append((round(time.time() - t_on, 2), running, float(m.get("allocator_frag_ratio", 0))))
            if running:
                ran, idle_since = True, None
            elif ran and idle_since is None:
                idle_since = time.time()
            if ran and idle_since and time.time() - idle_since >= 2.0:
                break
        defrag_s = (idle_since or time.time()) - t_on
        ps = pr.stop()
        smp.stop.set()
        smp.join()
        smp.poll()
        main_cpu = thread_cpu_s(p.pid) - main0
        m1, s1 = ctl.info("memory"), ctl.info("stats")
        hist = ctl.cmd("LATENCY", "HISTORY", "active-defrag-cycle") or []
        cyc = [int(h[1]) for h in hist]
        rows = ps.pop("rows")
        json.dump(rows, open(f"{D}/data/probe-{arm}-r{rep}.json", "w"))
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "N": N, "load_s": round(load_s, 2),
                "debug_object": dbg[:200], "frag_before": frag0, "frag_after": float(m1.get("allocator_frag_ratio", 0)),
                "defrag_ran": ran, "defrag_s": round(defrag_s, 2), "defrag_hits": int(s1.get("active_defrag_hits", 0)),
                **ps, "server_cpu_s": round(smp.cpu_s(), 3), "main_thread_cpu_s": round(main_cpu, 3),
                "server_peak_rss_mb": round(smp.peak / 1024, 1),
                "rss_mb_before": round(int(m0["used_memory_rss"]) / 2**20, 1),
                "rss_mb_after": round(int(m1["used_memory_rss"]) / 2**20, 1),
                "defrag_cycle_events": len(cyc), "defrag_cycle_max_ms": max(cyc) if cyc else 0,
                "defrag_cycle_ms_top": sorted(cyc, reverse=True)[:20], "trace": trace[:300]}
    finally:
        stop(p)
        log.close()


SHOW = ("arm", "rep", "frag_before", "frag_after", "defrag_s", "defrag_hits", "raw_max_ms", "cor_p999_ms",
        "raw_over_100ms", "blocked_ms", "defrag_cycle_max_ms", "server_cpu_s", "server_peak_rss_mb")


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    os.makedirs(f"{D}/logs", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in SHOW}), flush=True)


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["raw_p50_ms", "raw_p99_ms", "raw_p999_ms", "raw_max_ms", "cor_p99_ms", "cor_p999_ms", "cor_max_ms",
            "raw_over_10ms", "raw_over_100ms", "blocked_ms", "defrag_cycle_events", "defrag_cycle_max_ms",
            "defrag_s", "defrag_hits", "frag_before", "frag_after", "server_cpu_s", "main_thread_cpu_s",
            "server_peak_rss_mb", "rss_mb_before", "rss_mb_after"]
    out = [f"# redis budget-checked-too-coarsely: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"Two lists of {rows[0]['N']:,} 100-byte items filled alternately at list-max-ziplist-size 5, one deleted, "
           "then active defrag on (hz 100, cycle 25%: a 2,500 us budget per cycle) while a 1 ms PING probe runs on its "
           "own core (raw: round trip; cor: from the scheduled send time). defrag_cycle_*: the server's LATENCY "
           "HISTORY active-defrag-cycle. mean, sd [min, max].", "", "| metric | parent | fix | parent / fix |",
           "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [float(r[k]) for r in rows if r["arm"] == arm]
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = means["parent"] / means["fix"] if means["fix"] else float("inf")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio:.2f} |")
    for arm in ("parent", "fix"):
        r = next(r for r in rows if r["arm"] == arm)
        out += ["", f"{arm}, rep {r['rep']}: `{r['debug_object']}`; longest defrag cycles (ms) "
                f"`{r['defrag_cycle_ms_top']}`"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"build": build, "measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5),
     "report": report}[sys.argv[1]]()

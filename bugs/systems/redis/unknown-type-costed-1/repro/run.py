#!/usr/bin/env python3
"""redis/unknown-type-costed-1 (queue rank 56): lazy free costs a stream as one allocation, so UNLINK frees it inline.

Bug (src/lazyfree.c at 43af28f5b487, lines 31-47 and 65-85): lazyfreeGetFreeEffort() has no OBJ_STREAM branch and
returns 1 ("Everything else is a single allocation"), below LAZYFREE_THRESHOLD (64), so dbAsyncDelete frees a stream
of any size on the main thread (freeStream: every rax node, listpack and consumer-group PEL entry), and every client
waits. Fixed upstream in 5b0a06af4899 (2020-08-25): a stream's effort is its rax node count plus its consumer groups'
PEL sizes, so a large stream goes to the lazyfree bio thread. Parent 43af28f5b487.

One run (fresh server per run, release builds from tools/reproduce/build.sh):
  1. CONFIG SET stream-node-max-entries 1, so each entry is its own rax node and listpack; XADD N entries to one
     stream (Lua batches); XLEN check;
  2. measured: a 1 ms PING probe (tools/reproduce/pingprobe.py) on its own core starts; 2 s later UNLINK s (or DEL s,
     MODE=del, the control: inline in both arms) from a second connection, timed; the window ends 3 s after
     lazyfree_pending_objects is back to 0; server CPU (all threads), main-thread CPU and peak RSS over the window.
Arms alternate per repetition.

    run.py build | measure [REPS] [MODE] | report
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

ARMS = {"parent": "43af28f5b487", "fix": "5b0a06af4899"}
PORT = 15442
N = int(os.environ.get("N", 3_000_000))
SERVER_CPU, PROBE_CPU = 2, 4


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


def one(arm, rep, mode):
    log = open(f"{D}/logs/{arm}-{mode}-r{rep}.log", "w")
    p = start(server(arm), PORT, [], log)
    try:
        pin(p.pid, SERVER_CPU)
        r = Resp(PORT, timeout=600)
        ok(r.cmd("CONFIG", "SET", "stream-node-max-entries", "1"))
        t0 = time.time()
        script = "for i=1,tonumber(ARGV[1]) do redis.call('XADD',KEYS[1],'*','f','v') end return 1"
        for lo in range(0, N, 100_000):
            ok(r.cmd("EVAL", script, "1", "s", str(min(N, lo + 100_000) - lo)))
        load_s = time.time() - t0
        xlen = ok(r.cmd("XLEN", "s"))
        m0 = r.info("memory")
        reset_hwm(p.pid)
        smp = Sampler(p.pid)
        smp.poll()
        smp.start()
        main0 = thread_cpu_s(p.pid)
        pr = Probe(PORT, 0.001, PROBE_CPU)
        pr.start()
        time.sleep(2.0)
        ctl = Resp(PORT, timeout=600)
        t_del = time.perf_counter()
        ok(ctl.cmd("UNLINK" if mode == "unlink" else "DEL", "s"))
        del_ms = (time.perf_counter() - t_del) * 1e3
        t1, pend, zero_at = time.time(), [], None
        while time.time() - t1 < 60:
            m = ctl.info("memory")
            n = int(m.get("lazyfree_pending_objects", 0))
            pend.append((round(time.time() - t1, 3), n, int(m["used_memory"])))
            if n == 0 and zero_at is None:
                zero_at = time.time()
            if zero_at and time.time() - zero_at >= 3.0:
                break
            time.sleep(0.05)
        free_s = (zero_at or time.time()) - t1
        ps = pr.stop()
        smp.stop.set()
        smp.join()
        smp.poll()
        main_cpu = thread_cpu_s(p.pid) - main0
        cs = ctl.info("commandstats")
        rows = ps.pop("rows")
        json.dump(rows, open(f"{D}/data/probe-{arm}-{mode}-r{rep}.json", "w"))
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "mode": mode, "N": N, "xlen": xlen,
                "load_s": round(load_s, 2), "used_memory_mb_before": round(int(m0["used_memory"]) / 2**20, 1),
                "del_call_ms": round(del_ms, 2), "free_done_s": round(free_s, 3),
                "pending_max": max(x[1] for x in pend), **ps,
                "server_cpu_s": round(smp.cpu_s(), 3), "main_thread_cpu_s": round(main_cpu, 3),
                "server_peak_rss_mb": round(smp.peak / 1024, 1),
                "cmdstat": cs.get(f"cmdstat_{mode}", ""), "pending": pend[:40]}
    finally:
        stop(p)
        log.close()


SHOW = ("arm", "mode", "rep", "xlen", "del_call_ms", "free_done_s", "raw_max_ms", "cor_p999_ms", "raw_over_100ms",
        "blocked_ms", "server_cpu_s", "main_thread_cpu_s", "server_peak_rss_mb")


def measure(reps, mode):
    os.makedirs(f"{D}/data", exist_ok=True)
    os.makedirs(f"{D}/logs", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, mode)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in SHOW}), flush=True)


def table(rows, keys):
    out = ["| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [r[k] for r in rows if r["arm"] == arm]
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = means["parent"] / means["fix"] if means["fix"] else float("inf")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio:.2f} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["del_call_ms", "raw_p50_ms", "raw_p99_ms", "raw_p999_ms", "raw_max_ms", "cor_p999_ms", "cor_max_ms",
            "raw_over_10ms", "raw_over_100ms", "blocked_ms", "free_done_s", "server_cpu_s", "main_thread_cpu_s",
            "server_peak_rss_mb", "used_memory_mb_before", "load_s"]
    out = [f"# redis unknown-type-costed-1: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"One stream of {rows[0]['N']:,} entries at stream-node-max-entries 1 (one rax node each), then deleted "
           "while a 1 ms PING probe runs on its own core (raw: round trip; cor: from the scheduled send time). "
           "del_call_ms: the deleting command's own round trip; free_done_s: until lazyfree_pending_objects is 0. "
           "mean, sd [min, max]."]
    for mode in ("unlink", "del"):
        sub = [r for r in rows if r["mode"] == mode]
        if sub:
            out += ["", f"## {mode.upper()}" + (" (the control: inline in both arms)" if mode == "del" else ""), ""]
            out += table(sub, keys)
    for r in rows[:2]:
        out += ["", f"{r['arm']} {r['mode']} rep {r['rep']}: xlen {r['xlen']}; `{r['cmdstat']}`; "
                f"lazyfree_pending_objects (s, n, used_memory) `{r['pending'][:6]}`"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"build": build,
     "measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5, sys.argv[3] if len(sys.argv) > 3 else "unlink"),
     "report": report}[sys.argv[1]]()

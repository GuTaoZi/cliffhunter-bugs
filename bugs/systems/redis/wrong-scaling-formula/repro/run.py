#!/usr/bin/env python3
"""redis/wrong-scaling-formula (queue rank 57): the fast expire cycle's time budget is 250 ms instead of 1 ms.

Bug (src/expire.c at 1ccc270a2cb3, lines 127-136): config_cycle_fast_duration = ACTIVE_EXPIRE_CYCLE_FAST_DURATION *
ACTIVE_EXPIRE_CYCLE_FAST_DURATION/4*effort, which is 1000*1000/4*1 = 250,000 us at the default effort 1. The fast
cycle runs from beforeSleep (server.c:2097-2098), on the main thread, whenever the previous cycle hit its time
limit, so a backlog of expired keys blocks every client for up to 250 ms at a time, every 500 ms (expire.c:163).
Fixed upstream in 2ab51a644d3d (2019-11-18): effort-1, and + instead of *, so 1000 + 250*(effort-1) = 1000 us.
Parent 1ccc270a2cb3.

One run (fresh server per run, release builds from tools/reproduce/build.sh):
  1. DEBUG SET-ACTIVE-EXPIRE 0; DEBUG POPULATE N; PEXPIRE every key 1 ms (Lua batches), sleep, so all N keys are
     logically expired and none is removed yet;
  2. measured: a 1 ms PING probe (tools/reproduce/pingprobe.py) on its own core starts; 1 s later
     DEBUG SET-ACTIVE-EXPIRE 1; the window ends 1 s after DBSIZE reaches 0 (at most 60 s);
     server CPU (all threads), main-thread CPU and peak RSS over the window; INFO stats every 500 ms;
     LATENCY HISTORY expire-cycle (the server's own record of each cycle over 10 ms).
Arms alternate per repetition.

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

ARMS = {"parent": "1ccc270a2cb3", "fix": "2ab51a644d3d"}
PORT = 15441
N = int(os.environ.get("N", 2_000_000))
SERVER_CPU, PROBE_CPU = 2, 4


def server(arm):
    return f"{ROOT}/build/redis-{ARMS[arm]}/src/src/redis-server"


def build():
    for arm, sha in ARMS.items():
        r = subprocess.run(["sh", f"{REPO}/tools/reproduce/build.sh", "redis", sha], capture_output=True, text=True)
        print(arm, sha, "rc", r.returncode, r.stdout.strip().split("\n")[-1][:120])


def pin(pid, cpu):
    for t in os.listdir(f"/proc/{pid}/task"):
        os.sched_setaffinity(int(t), {cpu})


def ok(v):
    if isinstance(v, Exception):
        raise v
    return v


def one(arm, rep):
    log = open(f"{D}/logs/{arm}-r{rep}.log", "w")
    p = start(server(arm), PORT, ["--hz", "10", "--latency-monitor-threshold", "10"], log)
    try:
        pin(p.pid, SERVER_CPU)
        r = Resp(PORT, timeout=600)
        ok(r.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "0"))
        t0 = time.time()
        ok(r.cmd("DEBUG", "POPULATE", str(N)))
        script = ("for i=tonumber(ARGV[1]),tonumber(ARGV[2]) do redis.call('PEXPIRE','key:'..i,1) end return 1")
        for lo in range(0, N, 200_000):
            ok(r.cmd("EVAL", script, "0", str(lo), str(min(N, lo + 200_000) - 1)))
        load_s = time.time() - t0
        time.sleep(0.5)
        ks = r.info("keyspace")
        r.cmd("CONFIG", "RESETSTAT")
        r.cmd("LATENCY", "RESET")
        reset_hwm(p.pid)
        smp = Sampler(p.pid)
        smp.poll()
        smp.start()
        main0 = thread_cpu_s(p.pid)
        pr = Probe(PORT, 0.001, PROBE_CPU)
        pr.start()
        time.sleep(1.0)
        ctl = Resp(PORT, timeout=600)
        t_on = time.time()
        ok(ctl.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "1"))
        stats, zero_at = [], None
        while time.time() - t_on < 60:
            time.sleep(0.5)
            s = ctl.info("stats")
            n = int(ctl.cmd("DBSIZE"))
            stats.append({"t": round(time.time() - t_on, 2), "dbsize": n,
                          "expired_keys": int(s.get("expired_keys", 0)),
                          "cap_reached": int(s.get("expired_time_cap_reached_count", 0))})
            if n == 0 and zero_at is None:
                zero_at = time.time()
            if zero_at and time.time() - zero_at >= 1.0:
                break
        drain_s = (zero_at or time.time()) - t_on
        ps = pr.stop()
        smp.stop.set()
        smp.join()
        smp.poll()
        main_cpu = thread_cpu_s(p.pid) - main0
        hist = ctl.cmd("LATENCY", "HISTORY", "expire-cycle") or []
        cyc = [int(h[1]) for h in hist]
        rows = ps.pop("rows")
        json.dump(rows, open(f"{D}/data/probe-{arm}-r{rep}.json", "w"))
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "N": N, "load_s": round(load_s, 2),
                "keyspace": ks.get("db0", ""), "drain_s": round(drain_s, 2), **ps,
                "server_cpu_s": round(smp.cpu_s(), 3), "main_thread_cpu_s": round(main_cpu, 3),
                "server_peak_rss_mb": round(smp.peak / 1024, 1),
                "expire_cycle_events": len(cyc), "expire_cycle_max_ms": max(cyc) if cyc else 0,
                "expire_cycle_ms": cyc, "expired_keys": stats[-1]["expired_keys"] if stats else None,
                "cap_reached": stats[-1]["cap_reached"] if stats else None, "stats": stats}
    finally:
        stop(p)
        log.close()


SHOW = ("arm", "rep", "drain_s", "raw_p50_ms", "raw_p99_ms", "raw_max_ms", "cor_p999_ms", "raw_over_100ms",
        "blocked_ms", "expire_cycle_max_ms", "server_cpu_s", "server_peak_rss_mb")


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


def table(rows, keys, title, setup):
    out = [title, "", setup + " mean, sd [min, max].", "", "| metric | parent | fix | parent / fix |",
           "|---|---|---|---|"]
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
    keys = ["raw_p50_ms", "raw_p99_ms", "raw_p999_ms", "raw_max_ms", "cor_p99_ms", "cor_p999_ms", "cor_max_ms",
            "raw_over_10ms", "raw_over_100ms", "blocked_ms", "expire_cycle_events", "expire_cycle_max_ms",
            "drain_s", "server_cpu_s", "main_thread_cpu_s", "server_peak_rss_mb"]
    out = table(rows, keys, f"# redis wrong-scaling-formula: parent {ARMS['parent']} vs fix {ARMS['fix']}",
                f"{rows[0]['N']:,} keys made logically expired with active expire off, then active expire on; a 1 ms "
                "PING probe on its own core over the window (raw: round trip; cor: from the scheduled send time). "
                "expire_cycle_*: the server's LATENCY HISTORY expire-cycle (cycles over 10 ms).")
    for arm in ("parent", "fix"):
        r = next(r for r in rows if r["arm"] == arm)
        out += ["", f"{arm}, rep {r['rep']}: keyspace before `{r['keyspace']}`; expire-cycle events (ms) "
                f"`{r['expire_cycle_ms'][:40]}`; expired_keys {r['expired_keys']}, time cap reached "
                f"{r['cap_reached']}"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"build": build, "measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5),
     "report": report}[sys.argv[1]]()

#!/usr/bin/env python3
"""redis/empty-sample-means-repeat (queue rank 76): active expire spins its whole time budget on a dict it may not sample.

Bug (src/expire.c at 02a87885e64c, activeExpireCycle): the loop scans a db with dbScan and stops when the cursor is 0
(296-299), then decides whether to repeat: repeat = data.sampled == 0 || expired*100/sampled > acceptable_stale
(308). A dict with fewer than 1% of its buckets filled is not sampled (isExpiryDictValidForSamplingCb, 146-157; db.c
1527), so dbScan returns at once with nothing sampled: sampled is 0, the loop repeats, and it runs until its time limit
(checked every 16 iterations, 342; stat_expired_time_cap_reached_count at 346): 25 ms per slow cycle at hz 10, and then
a fast cycle in beforeSleep too (timelimit_exit stays set). Such a dict arises when a large expires dict is emptied
while a fork child lives: the resize policy is AVOID, cron does not rehash, the shrink's rehash advances one bucket
per touch, and elements / (size0 + size1) stays below 1%. Fixed in f20774eced7e (2024-02-05, "Fix active expire
timeout when db done the scanning (#13030)"): db_done = 1 when the cursor is 0 (298-299) and repeat = db_done ? 0 :
(...) (313). Parent 02a87885e64c. Design: data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (pinned to CPU 2; hz 10, dynamic-hz off, debug command on, rdb-key-save-delay 10 s so a
BGSAVE child lives for the whole run), 300,000 keys SET with EX 3600 (expires table 524,288 buckets), BGSAVE, then all
but 300 keys deleted, 3 s to settle, then a 30 s window: a PING every 1 ms from its own process (pinned to CPU 3,
tools/reproduce/pingprobe.py: raw and schedule-corrected latency), INFO stats deltas (expired_time_cap_reached_count
is the decision, expire_cycle_cpu_milliseconds its cost), the main thread's CPU, and the server's CPU and peak RSS
(tools/reproduce/measure.py). control: the same without BGSAVE (cron shrinks the dict; both arms should be flat).
Arms alternate per repetition; SHUTDOWN NOSAVE ends the run and any fork child left is killed.

    run.py measure REPS | control REPS | report
"""
import json
import os
import signal
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
from respclient import Resp, start  # noqa: E402
from pingprobe import Probe, thread_cpu_s  # noqa: E402

ARMS = {"parent": "02a87885e64c", "fix": "f20774eced7e"}
PORT = 15472
NKEYS, KEEP, SECS = 300_000, 300, 30


def binary(arm):
    return f"{ROOT}/build/redis-{ARMS[arm]}/src/src/redis-server"


def children(pid):
    out = []
    for t in os.listdir(f"/proc/{pid}/task"):
        try:
            out += [int(x) for x in open(f"/proc/{pid}/task/{t}/children").read().split()]
        except OSError:
            pass
    return out


def htstats(r):
    return r.cmd("DEBUG", "HTSTATS", "0").decode(errors="replace")


def stats(r, keys=("expired_time_cap_reached_count", "expire_cycle_cpu_milliseconds", "expired_keys")):
    i = r.info("stats")
    return {k: int(i.get(k, 0)) for k in keys}


def one(arm, rep, fork):
    tag = f"{'' if fork else 'control-'}{arm}-r{rep}"
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(rd)
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "fork": fork}
    with open(f"{D}/data/{tag}.log", "w") as log:
        p = start(binary(arm), PORT, ["--dir", rd, "--hz", "10", "--dynamic-hz", "no", "--enable-debug-command", "yes",
                                      "--rdb-key-save-delay", "10000000", "--latency-monitor-threshold", "5"], log)
        os.sched_setaffinity(p.pid, {2})
        kids = []
        try:
            r = Resp(PORT)
            for b in range(0, NKEYS, 20000):
                r.send([["SET", f"k{i}", "v", "EX", 3600] for i in range(b, min(b + 20000, NKEYS))])
            ks = r.info("keyspace").get("db0", "")
            for _ in range(150):
                if "rehashing target" not in htstats(r):
                    break
                time.sleep(0.2)
            row["keyspace_loaded"] = ks
            if fork:
                r.cmd("BGSAVE")
                for _ in range(100):
                    if r.info("persistence").get("rdb_bgsave_in_progress") == "1":
                        break
                    time.sleep(0.05)
                kids = children(p.pid)
            for b in range(KEEP, NKEYS, 20000):
                r.send([["DEL", f"k{i}"] for i in range(b, min(b + 20000, NKEYS))])
            time.sleep(3)
            ht = htstats(r)
            row["expires_ht"] = ht[ht.find("[Expires HT]"):][:400]
            row["expires_stuck"] = "rehashing target" in row["expires_ht"]
            row["bgsave_in_progress_start"] = r.info("persistence").get("rdb_bgsave_in_progress")
            s0, c0 = stats(r), thread_cpu_s(p.pid)
            m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--pid", str(p.pid), "--seconds",
                                  str(SECS)], stdout=subprocess.PIPE, text=True)
            pr = Probe(PORT, 0.001, cpu=3)
            pr.start()
            time.sleep(SECS)
            s = pr.stop()
            meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
            s1, c1 = stats(r), thread_cpu_s(p.pid)
            row.update({k: v for k, v in s.items() if k != "rows"})
            row.update({f"d_{k}": s1[k] - s0[k] for k in s0})
            row.update({"main_thread_cpu_s": round(c1 - c0, 3), "server_cpu_s": meas.get("cpu_s"),
                        "server_peak_rss_mb": meas.get("peak_rss_mb"),
                        "bgsave_in_progress_end": r.info("persistence").get("rdb_bgsave_in_progress"),
                        "latency_latest": [x if not isinstance(x, list) else [str(y) for y in x]
                                           for x in (r.cmd("LATENCY", "LATEST") or [])]})
            json.dump(s["rows"], open(f"{D}/data/{tag}-ping.json", "w"))
            try:
                r.cmd("SHUTDOWN", "NOSAVE")
            except (ConnectionError, OSError):
                pass
        finally:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            for k in kids:
                try:
                    os.kill(k, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    return row


def measure(reps, fork=True):
    os.makedirs(f"{D}/data", exist_ok=True)
    runs = f"{D}/data/runs.jsonl"
    done = [json.loads(l) for l in open(runs)] if os.path.exists(runs) else []
    start = max([r["rep"] for r in done if r["fork"] == fork] or [0]) + 1     # later sessions continue the count
    with open(runs, "a") as f:
        for rep in range(start, start + reps):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, fork)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in ("arm", "rep", "fork", "expires_stuck", "raw_p50_ms",
                                                          "cor_p99_ms", "raw_max_ms", "raw_over_10ms",
                                                          "d_expired_time_cap_reached_count",
                                                          "d_expire_cycle_cpu_milliseconds", "main_thread_cpu_s",
                                                          "server_peak_rss_mb", "bgsave_in_progress_end")}), flush=True)


def table(rows, keys):
    out = ["| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [float(r[k]) for r in rows if r["arm"] == arm and r.get(k) is not None]
            if not v:
                cells.append("n/a")
                means[arm] = None
                continue
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = (f"{means['parent'] / means['fix']:.2f}" if means["parent"] is not None and means["fix"] else "")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["raw_p50_ms", "raw_p99_ms", "raw_p999_ms", "raw_max_ms", "cor_p50_ms", "cor_p99_ms", "cor_p999_ms",
            "cor_max_ms", "raw_over_10ms", "blocked_ms", "d_expired_time_cap_reached_count",
            "d_expire_cycle_cpu_milliseconds", "main_thread_cpu_s", "server_cpu_s", "server_peak_rss_mb"]
    out = [f"# redis empty-sample-means-repeat: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"{NKEYS:,} keys with a TTL, a BGSAVE child kept alive, all but {KEEP} keys deleted, then {SECS} s of a PING "
           "every 1 ms (raw_*: round trip; cor_*: from the time each PING was due; blocked_ms: time beyond 1 ms the "
           "server did not answer). d_*: INFO stats deltas over the window. control: no BGSAVE. mean, sd [min, max].", ""]
    for fork, name in ((True, "With a fork child (the trigger)"), (False, "Control: no fork child")):
        rs = [r for r in rows if r["fork"] == fork]
        if rs:
            out += [f"## {name}", "", f"expires dict stuck mid-rehash: {sum(r['expires_stuck'] for r in rs)} of "
                    f"{len(rs)} runs", ""] + table(rs, keys) + [""]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"measure": lambda: measure(int(a[1])), "control": lambda: measure(int(a[1]), fork=False),
     "report": report}[a[0]]()

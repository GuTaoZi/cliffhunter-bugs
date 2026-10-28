#!/usr/bin/env python3
"""valkey/key-count-only-bound (queue rank 39): tracking-table eviction is bounded by a key count that grows per call.

Bug (src/tracking.c at 3293091659be, trackingLimitUsedSlots, lines 519-555): when the tracking table holds more than
tracking-table-max-keys keys, each call evicts effort = 100 * (timeout_counter + 1) keys (531), and the counter grows
on every call that does not reach the limit (554). Evicting a key sends an invalidation push to every client that
tracks it (373-424), so a call costs keys x clients with no time bound, and it runs before every command
(server.c:4894) and in serverCron (server.c:1790). Fixed upstream in 9b270b6d8b1a (2026-09-30): the loop also stops
after TRACKING_EVICTION_TIME_LIMIT_US (500 us). Parent 3293091659be.

One run (fresh server per run, release builds from tools/reproduce/build.sh):
  1. DEBUG POPULATE K; C clients, each HELLO 3, CLIENT TRACKING ON, MGET of all K keys (RESP3 clients: RESP2 ones
     without redirect get no push, tracking.c:307), so the table holds K keys with C clients each;
  2. measured: a 1 ms PING probe (tools/reproduce/pingprobe.py) on its own core; 1 s later CONFIG SET
     tracking-table-max-keys 10; the window ends 2 s after tracking_total_keys is at most 10 (at most 30 s);
     server CPU, main-thread CPU and peak RSS over the window. The tracking clients are not read during the window
     (their pushes wait in the kernel and server buffers).
Arms alternate per repetition.

    run.py build | measure [REPS] | report
"""
import json
import os
import socket
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

ARMS = {"parent": "3293091659be", "fix": "9b270b6d8b1a"}
PORT = 15444
K = int(os.environ.get("K", 10_000))
C = int(os.environ.get("C", 300))
SERVER_CPU, PROBE_CPU = 2, 4


def server(arm):
    return f"{ROOT}/build/valkey-{ARMS[arm]}/src/src/valkey-server"


def build():
    for arm, sha in ARMS.items():
        r = subprocess.run(["sh", f"{REPO}/tools/reproduce/build.sh", "valkey", sha], capture_output=True, text=True)
        print(arm, sha, "rc", r.returncode, r.stdout.strip().split("\n")[-1][:120])


def ok(v):
    if isinstance(v, Exception):
        raise v
    return v


def pin(pid, cpu):
    for t in os.listdir(f"/proc/{pid}/task"):
        os.sched_setaffinity(int(t), {cpu})


def resp(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for a in args:
        a = a if isinstance(a, bytes) else str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(a), a))
    return b"".join(out)


def trackers():
    mget = resp("MGET", *[f"key:{i}" for i in range(K)])
    socks = []
    for _ in range(C):
        s = socket.create_connection(("127.0.0.1", PORT))
        s.sendall(resp("HELLO", 3) + resp("CLIENT", "TRACKING", "ON") + mget + resp("PING"))
        socks.append(s)
    for s in socks:
        buf = b""
        while not buf.endswith(b"+PONG\r\n"):
            chunk = s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("tracker closed")
            buf = buf[-16:] + chunk if len(buf) > 1 << 16 else buf + chunk
    return socks


def one(arm, rep):
    log = open(f"{D}/logs/{arm}-r{rep}.log", "w")
    p = start(server(arm), PORT, ["--enable-debug-command", "yes", "--maxclients", "2000", "--dir", f"{D}/logs"], log)
    socks = []
    try:
        pin(p.pid, SERVER_CPU)
        r = Resp(PORT, timeout=600)
        ok(r.cmd("DEBUG", "POPULATE", str(K)))
        t0 = time.time()
        socks = trackers()
        load_s = time.time() - t0
        s0 = r.info("stats")
        keys0, items0 = int(s0["tracking_total_keys"]), int(s0["tracking_total_items"])
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
        ok(ctl.cmd("CONFIG", "SET", "tracking-table-max-keys", "10"))
        trace, low_at = [], None
        while time.time() - t_on < 30:
            time.sleep(0.1)
            n = int(ctl.info("stats")["tracking_total_keys"])
            trace.append((round(time.time() - t_on, 2), n))
            if n <= 10 and low_at is None:
                low_at = time.time()
            if low_at and time.time() - low_at >= 2.0:
                break
        evict_s = (low_at or time.time()) - t_on
        ps = pr.stop()
        smp.stop.set()
        smp.join()
        smp.poll()
        main_cpu = thread_cpu_s(p.pid) - main0
        s1 = ctl.info("stats")
        rows = ps.pop("rows")
        json.dump(rows, open(f"{D}/data/probe-{arm}-r{rep}.json", "w"))
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "K": K, "C": C, "load_s": round(load_s, 2),
                "tracking_keys_before": keys0, "tracking_items_before": items0,
                "tracking_keys_after": int(s1["tracking_total_keys"]), "evict_done_s": round(evict_s, 2), **ps,
                "server_cpu_s": round(smp.cpu_s(), 3), "main_thread_cpu_s": round(main_cpu, 3),
                "server_peak_rss_mb": round(smp.peak / 1024, 1), "trace": trace}
    finally:
        for s in socks:
            s.close()
        stop(p)
        log.close()


SHOW = ("arm", "rep", "tracking_items_before", "tracking_keys_after", "evict_done_s", "raw_p50_ms", "raw_max_ms",
        "cor_p999_ms", "raw_over_10ms", "blocked_ms", "server_cpu_s", "server_peak_rss_mb")


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
            "raw_over_10ms", "raw_over_100ms", "blocked_ms", "evict_done_s", "tracking_keys_after", "server_cpu_s",
            "main_thread_cpu_s", "server_peak_rss_mb"]
    out = [f"# valkey key-count-only-bound: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"{rows[0]['C']} RESP3 clients each tracking the same {rows[0]['K']:,} keys "
           f"({rows[0]['tracking_items_before']:,} tracking items), then CONFIG SET tracking-table-max-keys 10 while a "
           "1 ms PING probe runs on its own core (raw: round trip; cor: from the scheduled send time). evict_done_s: "
           "until tracking_total_keys is at most 10. mean, sd [min, max].", "", "| metric | parent | fix | parent / fix |",
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
        out += ["", f"{arm}, rep {r['rep']}: tracking_total_keys over time (s, keys) `{r['trace'][:12]}`"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"build": build, "measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5),
     "report": report}[sys.argv[1]]()

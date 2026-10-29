#!/usr/bin/env python3
"""valkey/banked-negative-overage (queue rank 83): time saved by empty defrag stages is banked and spent in one burst.

Bug (src/defrag.c at 1acf7f71c032): after each run of the defrag timer proc the overage, end time minus intended end
time, is added to defrag.timeproc_overage_us without limit (1179-1180), and the next run's duty is
P * waited / (100 - P) minus that overage (1158-1161), floored at active_defrag_cycle_us (1164-1167). A stage that
has nothing to do (an empty database's keys or expires) ends at once and banks almost its whole duty as negative
overage, which lengthens the next duty; after many empty stages the first stage with real work gets a duty of many
milliseconds and runs it in one event-loop call (logged as the latency event active-defrag-cycle, 1242). Fixed in
0c8ad5cd3412 (2024-12-11, "defrag: allow defrag to start during AOF loading (#1420)"): the banked overage is clamped
at 0 (1183); the commit also starts defrag from defragWhileBlocked (1261), which this workload never reaches.
Parent 1acf7f71c032. Design: data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (pinned to CPU 2; 16 databases, defrag effort pinned at 1% with active-defrag-cycle-min and
-max 1, verbose log), 2,000,000 keys of 100 bytes in db15 only (DEBUG POPULATE), every other one unlinked
(fragmentation of at least 1.4), then a 46 s phase: a PING every 1 ms from its own process (pinned to CPU 6), and ten
defrag restarts (activedefrag yes for 4 s, no for 0.3 s), each of which begins a cycle at db0 and so passes 30 empty
stages before db15. The server's CPU and peak RSS over the phase (tools/reproduce/measure.py); LATENCY HISTORY
active-defrag-cycle afterwards. Arms alternate per repetition.

    run.py check | measure REPS | report
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
from respclient import Resp, start  # noqa: E402
from pingprobe import Probe  # noqa: E402

ARMS = {"parent": "1acf7f71c032", "fix": "0c8ad5cd3412"}
PORT = 15474
NKEYS, RESTARTS = 2_000_000, 10


def serve(arm, rd, log):
    p = start(f"{ROOT}/build/valkey-{ARMS[arm]}/src/src/valkey-server", PORT,
              ["--dir", rd, "--enable-debug-command", "yes", "--loglevel", "verbose", "--logfile", f"{rd}/valkey.log",
               "--latency-monitor-threshold", "5", "--activedefrag", "no", "--active-defrag-cycle-min", "1",
               "--active-defrag-cycle-max", "1", "--active-defrag-ignore-bytes", "1mb"], log)
    os.sched_setaffinity(p.pid, {2})
    return p


def prepare(r):
    r.cmd("SELECT", 15)
    r.cmd("DEBUG", "POPULATE", NKEYS, "k", 100)
    for b in range(1, NKEYS, 500_000):
        r.send([["UNLINK", *[f"k:{i}" for i in range(c, min(c + 1000, b + 500_000, NKEYS), 2)]]
                for c in range(b, min(b + 500_000, NKEYS), 1000)])
    time.sleep(1)
    m = r.info("memory")
    ks = r.info("keyspace")
    return {"frag_ratio": float(m["allocator_frag_ratio"]), "frag_bytes": int(m["allocator_frag_bytes"]),
            "keyspace": {k: v for k, v in ks.items() if k.startswith("db")}}


def history(r):
    h = r.cmd("LATENCY", "HISTORY", "active-defrag-cycle") or []
    return [int(x[1]) for x in h]


def starts(rd):
    try:
        return sum("Starting active defrag" in l for l in open(f"{rd}/valkey.log", errors="replace"))
    except OSError:
        return 0


def one(arm, rep):
    tag = f"{arm}-r{rep}"
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(rd)
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep}
    with open(f"{D}/data/{tag}.out", "w") as log:
        p = serve(arm, rd, log)
        try:
            r = Resp(PORT)
            row.update(prepare(r))
            secs = 2 + RESTARTS * 4.3 + 1
            m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--pid", str(p.pid), "--seconds",
                                  str(int(secs))], stdout=subprocess.PIPE, text=True)
            pr = Probe(PORT, 0.001, cpu=6)
            pr.start()
            time.sleep(2)
            for _ in range(RESTARTS):
                r.cmd("CONFIG", "SET", "activedefrag", "yes")
                time.sleep(4.0)
                r.cmd("CONFIG", "SET", "activedefrag", "no")
                time.sleep(0.3)
            time.sleep(1)
            s = pr.stop()
            meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
            i = r.info("all")
            hist = history(r)
            row.update({k: v for k, v in s.items() if k != "rows"})
            row.update({"defrag_cycle_events_ms": hist, "defrag_cycle_max_ms": max(hist) if hist else 0,
                        "defrag_starts": starts(rd), "active_defrag_hits": int(i.get("active_defrag_hits", 0)),
                        "total_active_defrag_time": int(i.get("total_active_defrag_time", 0)),
                        "server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb")})
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
    return row


def check():
    out = []
    for arm in ARMS:
        rd = f"{D}/runs/check-{arm}-{int(time.time())}"
        os.makedirs(rd)
        with open(f"{D}/data/check-{arm}.out", "w") as log:
            p = serve(arm, rd, log)
            try:
                r = Resp(PORT)
                row = {"arm": arm, **prepare(r)}
                r.cmd("CONFIG", "SET", "activedefrag", "yes")
                time.sleep(3)
                row.update({"latency_latest": [[str(y) for y in x] for x in (r.cmd("LATENCY", "LATEST") or [])],
                            "active_defrag_running": r.info("memory").get("active_defrag_running"),
                            "defrag_starts": starts(rd)})
                out.append(row)
                r.cmd("SHUTDOWN", "NOSAVE")
            except (ConnectionError, OSError):
                pass
            finally:
                p.wait()
    json.dump(out, open(f"{D}/data/check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in ("arm", "rep", "frag_ratio", "raw_max_ms", "raw_over_10ms",
                                                          "blocked_ms", "cor_p999_ms", "defrag_cycle_max_ms",
                                                          "defrag_starts", "server_cpu_s", "server_peak_rss_mb")}),
                      flush=True)


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
    keys = ["raw_max_ms", "raw_p999_ms", "cor_p999_ms", "raw_over_10ms", "blocked_ms", "defrag_cycle_max_ms",
            "defrag_starts", "frag_ratio", "active_defrag_hits", "total_active_defrag_time", "server_cpu_s",
            "server_peak_rss_mb"]
    out = [f"# valkey banked-negative-overage: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"{NKEYS:,} keys in db15 only, every other one unlinked; defrag effort pinned at 1%; {RESTARTS} defrag "
           "restarts in 46 s, each passing 30 empty stages before db15, with a PING every 1 ms (raw_*: round trip; "
           "cor_*: from the time each PING was due; blocked_ms: time beyond 1 ms the server did not answer). "
           "defrag_cycle_max_ms: the largest active-defrag-cycle latency event. mean, sd [min, max].", ""] + table(rows, keys)
    if os.path.exists(f"{D}/data/check.json"):
        out += ["", "## Decision check: LATENCY LATEST 3 s after enabling defrag", "", "```",
                json.dumps([{k: c.get(k) for k in ("arm", "latency_latest", "active_defrag_running")}
                            for c in json.load(open(f"{D}/data/check.json"))], indent=1), "```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"check": check, "measure": lambda: measure(int(a[1])), "report": report}[a[0]]()

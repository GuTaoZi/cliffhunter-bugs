#!/usr/bin/env python3
"""valkey/forced-synchronous-catch-up (queue rank 84): a resize asked for mid-rehash finishes the whole rehash at once.

Bug (src/hashtable.c at dcbaecddce5d): resize() (reached from hashtableExpandIfNeeded on insert, 1272-1277) handles a
table that is still rehashing by running every remaining rehash step in a loop, `while (hashtableIsRehashing(ht))
rehashStep(ht);` (629), unless rehashing is paused (628), and then starts the new resize; expand() refuses only a
smaller size (679-680). A set, hash or zset's own table has no cron rehash and moves one bucket per insert, so after
a shrink (below 13% fill, MIN_FILL_PERCENT_SOFT at 90) the refill can overflow the new, smaller table before the
rehash out of the old one is done; the insert that overflows it then moves every remaining entry inside one command.
Fixed in aefed3d363d1 (2025-08-15, "Don't allow resize hashtable if rehashing is ongoing (#2465)"): resize asserts
it is not rehashing (606), expand() and hashtableExpandIfNeeded() refuse while rehashing (672, 1264), so the rehash
goes on one step per insert. Parent dcbaecddce5d. Design: data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (pinned to CPU 2), a set S of N0 members m0.. (hashtable-encoded: string members), exactly
N0 - T of them removed with SREM so the table shrinks at fill T (the shrink's rehash then starts), then, measured,
closed-loop SADDs of 100 new members each, timed per command, with a PING every 1 ms from its own process (pinned to
CPU 6); the server's CPU (/proc/PID/stat) and peak RSS (VmHWM, reset at the phase's start) over the phase, LATENCY HISTORY fast-command, and
DEBUG HTSTATS-KEY S before and after. Sizes (B, the table's buckets before the shrink): check 2^18 (N0 1,500,000,
T 238,551, 230,000 inserts), measure 2^21 (N0 10,000,000, T 1,908,408, 2,300,000 inserts).

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
from pingprobe import Probe, reset_hwm  # noqa: E402

ARMS = {"parent": "dcbaecddce5d", "fix": "aefed3d363d1"}
PORT = 15477
SIZES = {"check": (1_500_000, 238_551, 230_000), "measure": (10_000_000, 1_908_408, 2_300_000)}


def cpu_s(pid):
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")


def hwm_mb(pid):
    for ln in open(f"/proc/{pid}/status"):
        if ln.startswith("VmHWM:"):
            return int(ln.split()[1]) / 1024


def serve(arm, rd, log):
    p = start(f"{ROOT}/build/valkey-{ARMS[arm]}/src/src/valkey-server", PORT,
              ["--dir", rd, "--enable-debug-command", "yes", "--latency-monitor-threshold", "20"], log)
    os.sched_setaffinity(p.pid, {2})
    return p


def batch(r, cmd, names, per=1000, pipe=20):
    for b in range(0, len(names), per * pipe):
        r.send([[cmd, "S", *names[c:c + per]] for c in range(b, min(b + per * pipe, len(names)), per)])


def htstats(r):
    v = r.cmd("DEBUG", "HTSTATS-KEY", "S")
    return v.decode(errors="replace") if isinstance(v, bytes) else str(v)


def one(arm, rep, size, tag):
    n0, t, inserts = SIZES[size]
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(rd)
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "size": size, "n0": n0, "t": t, "inserts": inserts}
    with open(f"{D}/data/{tag}.out", "w") as log:
        p = serve(arm, rd, log)
        try:
            r = Resp(PORT, timeout=600)
            t0 = time.time()
            batch(r, "SADD", [f"m{i}" for i in range(n0)])
            row["ht_built"] = htstats(r)[:600]
            batch(r, "SREM", [f"m{i}" for i in range(n0 - t)])
            row["load_s"] = round(time.time() - t0, 1)
            row["ht_shrunk"] = htstats(r)[:600]
            row["shrink_started"] = "rehashing target" in row["ht_shrunk"]
            reset_hwm(p.pid)
            c0 = cpu_s(p.pid)
            pr = Probe(PORT, 0.001, cpu=6)
            pr.start()
            time.sleep(0.5)
            lat = []
            for j in range(0, inserts, 100):
                args = ["SADD", "S", *[f"n{j + i}" for i in range(100)]]
                a = time.perf_counter()
                r.cmd(*args)
                lat.append(time.perf_counter() - a)
            time.sleep(0.5)
            s = pr.stop()
            meas = {"cpu_s": round(cpu_s(p.pid) - c0, 2), "peak_rss_mb": hwm_mb(p.pid)}
            top = sorted(range(len(lat)), key=lambda i: -lat[i])[:3]
            hist = r.cmd("LATENCY", "HISTORY", "fast-command") or []
            row.update({"sadd_max_ms": lat[top[0]] * 1e3, "sadd_max_at_cmd": top[0],
                        "sadd_top3_ms": [round(lat[i] * 1e3, 2) for i in top], "sadd_top3_at": top,
                        "sadd_p50_ms": sorted(lat)[len(lat) // 2] * 1e3, "sadd_total_s": round(sum(lat), 2),
                        "fast_command_events_ms": [int(x[1]) for x in hist], "ht_after": htstats(r)[:600],
                        "server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb")})
            row.update({k: v for k, v in s.items() if k != "rows"})
            json.dump({"sadd_s": lat, "ping": s["rows"]}, open(f"{D}/data/{tag}-lat.json", "w"))
            try:
                r.cmd("SHUTDOWN", "NOSAVE")
            except (ConnectionError, OSError):
                pass
        finally:
            try:
                p.wait(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    return row


SHOW = ("arm", "rep", "size", "load_s", "shrink_started", "sadd_max_ms", "sadd_max_at_cmd", "sadd_top3_ms", "raw_max_ms",
        "blocked_ms", "fast_command_events_ms", "server_cpu_s", "server_peak_rss_mb")


def check():
    os.makedirs(f"{D}/data", exist_ok=True)
    out = []
    for arm in ARMS:
        row = one(arm, 0, "check", f"check-{arm}")
        out.append({k: row.get(k) for k in SHOW + ("ht_shrunk", "ht_after")})
    json.dump(out, open(f"{D}/data/check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, "measure", f"{arm}-r{rep}")
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in SHOW}), flush=True)


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
    keys = ["sadd_max_ms", "sadd_max_at_cmd", "sadd_p50_ms", "sadd_total_s", "raw_max_ms", "raw_p999_ms", "blocked_ms",
            "raw_over_100ms", "server_cpu_s", "server_peak_rss_mb", "load_s"]
    n0, t, ins = SIZES["measure"]
    out = [f"# valkey forced-synchronous-catch-up: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"A set of {n0:,} string members shrunk with SREM to exactly {t:,} (the 13% threshold of its "
           f"2^21-bucket table), then {ins:,} new members added by closed-loop SADDs of 100, with a PING every 1 ms. "
           "sadd_*: per-command latency (max, the command index where it fell, median, total); raw_*/blocked_ms: the "
           "PINGs. mean, sd [min, max].", ""] + table(rows, keys)
    if os.path.exists(f"{D}/data/check.json"):
        out += ["", "## Check (2^18 buckets)", "", "```", json.dumps(
            [{k: c.get(k) for k in ("arm", "sadd_max_ms", "sadd_max_at_cmd", "sadd_top3_ms")}
             for c in json.load(open(f"{D}/data/check.json"))], indent=1), "```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"check": check, "measure": lambda: measure(int(a[1])), "report": report}[a[0]]()

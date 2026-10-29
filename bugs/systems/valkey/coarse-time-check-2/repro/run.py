#!/usr/bin/env python3
"""valkey/coarse-time-check-2 (queue rank 106): hash-field expiry reads the clock every 16 passes and overruns its slice.

Bug (src/expire.c at cef8822f60b6, activeExpireCycleJob): the time limit is checked only when (iteration & 0xf) == 0
(392-398), every 16 passes, for keys and for hash fields alike; a fields pass can expire up to 20 keys x 80 fields
(264, 314), so 16 passes of a fields job are thousands of field deletions. The fast cycle has a 1,000 us limit (459,
465) and runs from beforeSleep after a cycle that hit its limit (227; server.c:1846); the slow cycle 25 ms at hz 10
(474-475). With many hashes whose fields expire together, each fast cycle runs several times its limit on the main
thread. Fixed in 3213f48fd694 (2025-09-10, "Increase frequency of time check during fields active expiration
(#2595)"): a per-job time_check_mask, 0xf for keys and 0 for fields (221, 279, 288, 400-407), so a fields job checks
the clock on every pass. Parent cef8822f60b6. Design: data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (pinned to CPU 2; hz 10, effort 1, latency-monitor-threshold 2), H hashes h:%05d of 1,000
fields with 32-byte values, every field set to expire at the same instant T (HSETEX ... PXAT T); from T-5 s a PING
every 1 ms from its own process (pinned to CPU 3) until the database is empty (DBSIZE 0, at most 60 s after T). The
latency over [T, drained] against [T-5, T) in the same run, the INFO stats deltas (expired_fields,
expired_time_cap_reached_count, expire_cycle_cpu_milliseconds), LATENCY HISTORY expire-cycle, the server's CPU and peak
RSS (tools/reproduce/measure.py). control: one hash of 5,000,000 fields (one key per pass, no overrun expected).

    run.py check | measure REPS | control REPS | report
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
from pingprobe import Probe, summary  # noqa: E402

ARMS = {"parent": "cef8822f60b6", "fix": "3213f48fd694"}
PORT = 15476
FIELDS, VAL = 1000, b"v" * 32
STATS = ("expired_fields", "expired_time_cap_reached_count", "expire_cycle_cpu_milliseconds", "expired_keys")


def serve(arm, rd, log):
    p = start(f"{ROOT}/build/valkey-{ARMS[arm]}/src/src/valkey-server", PORT,
              ["--dir", rd, "--latency-monitor-threshold", "2"], log)
    os.sched_setaffinity(p.pid, {2})
    return p


def load(r, hashes, fields, t_ms):
    names = [b"f%07d" % j for j in range(fields)]
    for h0 in range(0, hashes, 50):
        cmds = []
        for h in range(h0, min(h0 + 50, hashes)):
            for f0 in range(0, fields, 1000):
                chunk = names[f0:f0 + 1000]
                args = ["HSETEX", f"h:{h:05d}", "PXAT", t_ms, "FIELDS", len(chunk)]
                for n in chunk:
                    args += [n, VAL]
                cmds.append(args)
        rep = r.send(cmds)
        bad = [x for x in rep if isinstance(x, Exception)]
        if bad:
            raise RuntimeError(f"HSETEX failed: {bad[0]}")


def stats(r):
    i = r.info("stats")
    return {k: int(i.get(k, 0)) for k in STATS}


def one(arm, rep, hashes, fields, lead_s, tag):
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(rd)
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "hashes": hashes, "fields": fields}
    with open(f"{D}/data/{tag}.out", "w") as log:
        p = serve(arm, rd, log)
        try:
            r = Resp(PORT)
            t_ms = int((time.time() + lead_s) * 1000)
            t0 = time.time()
            load(r, hashes, fields, t_ms)
            row["load_s"] = round(time.time() - t0, 1)
            row["load_margin_s"] = round(t_ms / 1000 - time.time(), 1)
            if row["load_margin_s"] < 8:
                row["aborted"] = "load not done by T-8 s"
                return row
            s_before = stats(r)
            row["expired_fields_before_T"] = s_before["expired_fields"]
            time.sleep(max(0, t_ms / 1000 - 5 - time.time()))
            m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--pid", str(p.pid), "--seconds",
                                  "65"], stdout=subprocess.PIPE, text=True)
            pr = Probe(PORT, 0.001, cpu=3)
            pr.start()
            time.sleep(max(0, t_ms / 1000 - time.time()))
            s0 = stats(r)
            drained = None
            while time.time() < t_ms / 1000 + 60:
                if r.cmd("DBSIZE") == 0:
                    drained = time.time()
                    break
                time.sleep(0.05)
            s1 = stats(r)
            s = pr.stop()
            end = drained or time.time()
            base = summary([x for x in s["rows"] if x[0] < t_ms / 1000])
            win = summary([x for x in s["rows"] if t_ms / 1000 <= x[0] <= end])
            hist = r.cmd("LATENCY", "HISTORY", "expire-cycle") or []
            row.update({f"base_{k}": v for k, v in base.items()})
            row.update({k: v for k, v in win.items()})
            row.update({f"d_{k}": s1[k] - s0[k] for k in STATS})
            row.update({"drain_s": round(end - t_ms / 1000, 2), "drained": drained is not None,
                        "expire_cycle_events_ms": [int(x[1]) for x in hist],
                        "expire_cycle_max_ms": max([int(x[1]) for x in hist] or [0])})
            meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
            row.update({"server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb")})
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


SHOW = ("arm", "rep", "hashes", "load_margin_s", "raw_p50_ms", "raw_p99_ms", "cor_p99_ms", "raw_max_ms", "blocked_ms",
        "expire_cycle_max_ms", "d_expired_fields", "d_expired_time_cap_reached_count", "drain_s", "server_cpu_s",
        "server_peak_rss_mb")


def measure(reps, control=False):
    os.makedirs(f"{D}/data", exist_ok=True)
    hashes, fields, lead = (1, 5_000_000, 120) if control else (10_000, FIELDS, 150)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                tag = f"{'control-' if control else ''}{arm}-r{rep}"
                row = one(arm, rep, hashes, fields, lead, tag)
                row["control"] = control
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in SHOW + ("aborted",)}), flush=True)


def check():
    os.makedirs(f"{D}/data", exist_ok=True)
    out = []
    for arm in ARMS:
        row = one(arm, 0, 2000, FIELDS, 40, f"check-{arm}")
        out.append({k: row.get(k) for k in SHOW + ("d_expire_cycle_cpu_milliseconds", "aborted")})
    json.dump(out, open(f"{D}/data/check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


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
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl") if "aborted" not in json.loads(l)]
    keys = ["raw_p50_ms", "raw_p99_ms", "raw_max_ms", "cor_p50_ms", "cor_p99_ms", "blocked_ms", "base_raw_p50_ms",
            "base_raw_p99_ms", "expire_cycle_max_ms", "d_expired_fields", "d_expired_time_cap_reached_count",
            "d_expire_cycle_cpu_milliseconds", "drain_s", "server_cpu_s", "server_peak_rss_mb"]
    out = [f"# valkey coarse-time-check-2: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           "Hashes whose fields all expire at the same instant T, a PING every 1 ms from T-5 s until the database is "
           "empty. raw_*/cor_*: the PINGs in [T, drained] (cor_: from the time each PING was due); base_*: [T-5, T) in "
           "the same run. d_*: INFO stats deltas over the drain. control: one hash of 5,000,000 fields. "
           "mean, sd [min, max].", ""]
    for control, name in ((False, "10,000 hashes of 1,000 fields (the trigger)"), (True, "Control: one hash of 5M fields")):
        rs = [r for r in rows if r.get("control") == control]
        if rs:
            out += [f"## {name}", ""] + table(rs, keys) + [""]
    if os.path.exists(f"{D}/data/check.json"):
        out += ["## Check: 2,000 hashes", "", "```", open(f"{D}/data/check.json").read().strip(), "```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"check": check, "measure": lambda: measure(int(a[1])), "control": lambda: measure(int(a[1]), True),
     "report": report}[a[0]]()

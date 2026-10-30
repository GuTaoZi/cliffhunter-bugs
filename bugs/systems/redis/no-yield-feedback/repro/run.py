#!/usr/bin/env python3
"""redis/no-yield-feedback (queue rank 78): active defrag keeps its full CPU effort on fragmentation it cannot fix.

Bug (src/defrag.c at dcd0b3d02013): computeDefragCycles (1027-1058) sets the effort from the current fragmentation
alone (cpu_pct = INTERPOLATE(frag_pct, lower, upper, cycle_min, cycle_max), clamped, stored in
server.active_defrag_running at 1053), and activeDefragCycle (1064) runs 1e6 * running / hz / 100 microseconds of
main-thread work per serverCron tick (1122). At the end of each scan pass (1160-1164) the effort is recomputed from
fragmentation again; hits, misses and whether fragmentation fell are never looked at, so memory the scan cannot move
(module values without a defrag callback, module.c 13880-13894) keeps the effort at its cap for ever. Fixed in
f86575f210a9 (2025-01-24, "Gradually reduce defrag CPU usage when defragmentation is ineffective (#13752)"): a
decay_rate (1075), multiplied into cpu_pct before the clamp (1044), times 0.9 after every pass that changed
fragmentation by 2 points or less with under 1% hits (1166-1181). Parent dcd0b3d02013. Design:
data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (pinned to CPU 2; hz 10, dynamic-hz off, one database, the datatype test module built from
the arm's own tree, verbose log), 200,000 DATATYPE.SET values of 400 bytes, every even key deleted (fragmentation that
the scan cannot move), defrag thresholds set from the measured fragmentation F (lower 1, upper 0.9 F, cycle-min 1,
cycle-max 50), then 80 s: CONFIG SET activedefrag yes at t=0, a PING every 1 ms from its own process (pinned to CPU
3), INFO memory and stats once a second (active_defrag_running is the decision), the server's CPU and peak RSS.
Latency per window: [0,10) s (the first pass, the same in both arms), [10,40) and [45,75) (steady state).

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
from pingprobe import Probe, summary, thread_cpu_s  # noqa: E402

ARMS = {"parent": "dcd0b3d02013", "fix": "f86575f210a9"}
PORT = 15473
NKEYS, VSIZE, SECS = int(os.environ.get("NKEYS", 200_000)), 400, 80
WINDOWS = ((0, 10), (10, 40), (45, 75))
FIELDS = ("active_defrag_running", "active_defrag_hits", "active_defrag_misses", "total_active_defrag_time",
          "allocator_frag_ratio", "allocator_frag_bytes")


def tree(arm):
    return f"{ROOT}/build/redis-{ARMS[arm]}/src"


def module(arm):
    so = f"{tree(arm)}/tests/modules/datatype.so"
    if not os.path.exists(so):
        subprocess.run(["sh", f"{REPO}/tools/reproduce/inenv.sh", "gcc gnumake",
                        f"make -C {tree(arm)}/tests/modules datatype.so"], check=True, capture_output=True)
    return so


def serve(arm, rd, log):
    p = start(f"{tree(arm)}/src/redis-server", PORT,
              ["--dir", rd, "--hz", "10", "--dynamic-hz", "no", "--databases", "1", "--loadmodule", module(arm),
               "--loglevel", "verbose", "--logfile", f"{rd}/redis.log", "--latency-monitor-threshold", "5",
               "--active-defrag-ignore-bytes", "100kb"], log)
    os.sched_setaffinity(p.pid, {2})
    return p


def prepare(r, nkeys):
    for b in range(0, nkeys, 10000):
        r.send([["DATATYPE.SET", f"k{i}", 1, "x" * VSIZE] for i in range(b, min(b + 10000, nkeys))])
    for b in range(0, nkeys, 20000):
        r.send([["DEL", f"k{i}"] for i in range(b, min(b + 20000, nkeys), 2)])
    time.sleep(1)
    m = r.info("memory")
    ratio = float(m["allocator_frag_ratio"])
    f = (ratio - 1) * 100
    upper = max(2, int(0.9 * f))
    for k, v in (("active-defrag-threshold-lower", 1), ("active-defrag-threshold-upper", upper),
                 ("active-defrag-cycle-min", 1), ("active-defrag-cycle-max", 50)):
        r.cmd("CONFIG", "SET", k, v)
    return {"frag_ratio_before": ratio, "frag_bytes_before": int(m["allocator_frag_bytes"]), "threshold_upper": upper}


def sample(r, pid):
    i = r.info("all")
    return {k: float(i.get(k, "nan")) for k in FIELDS} | {"main_cpu_s": thread_cpu_s(pid), "t": time.time()}


def passes(rd):
    try:
        lines = open(f"{rd}/redis.log", errors="replace").read().splitlines()
    except OSError:
        return []
    return [l.split(" * ", 1)[-1] for l in lines if "Starting active defrag" in l or "Active defrag done" in l]


def one(arm, rep):
    tag = f"{arm}-r{rep}"
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(rd)
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "nkeys": NKEYS}
    with open(f"{D}/data/{tag}.out", "w") as log:
        p = serve(arm, rd, log)
        try:
            r = Resp(PORT)
            row.update(prepare(r, NKEYS))
            m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--pid", str(p.pid), "--seconds",
                                  str(SECS)], stdout=subprocess.PIPE, text=True)
            pr = Probe(PORT, 0.001, cpu=3)
            pr.start()
            time.sleep(0.5)
            r.cmd("CONFIG", "SET", "activedefrag", "yes")
            t0 = time.time()
            series = []
            while time.time() < t0 + SECS - 1:
                series.append(sample(r, p.pid))
                time.sleep(max(0, 1 - (time.time() - series[-1]["t"])))
            s = pr.stop()
            meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
            for a, b in WINDOWS:
                sl = summary([x for x in s["rows"] if t0 + a <= x[0] < t0 + b])
                row.update({f"w{a}_{k}": v for k, v in sl.items()})
                ss = [x for x in series if t0 + a <= x["t"] < t0 + b]
                if len(ss) > 1:
                    row[f"w{a}_effort_mean"] = st.mean(x["active_defrag_running"] for x in ss)
                    row[f"w{a}_main_cpu_frac"] = (ss[-1]["main_cpu_s"] - ss[0]["main_cpu_s"]) / (ss[-1]["t"] - ss[0]["t"])
            row.update({"server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb"),
                        "hits_end": series[-1]["active_defrag_hits"], "misses_end": series[-1]["active_defrag_misses"],
                        "frag_ratio_end": series[-1]["allocator_frag_ratio"], "passes": passes(rd)[:40]})
            json.dump({"t0": t0, "series": series, "ping": s["rows"]}, open(f"{D}/data/{tag}-series.json", "w"))
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
    """20,000 live keys, defrag on for 15 s: the parent's effort repeats, the fix's steps down pass by pass."""
    out = []
    for arm in ARMS:
        rd = f"{D}/runs/check-{arm}-{int(time.time())}"
        os.makedirs(rd)
        with open(f"{D}/data/check-{arm}.out", "w") as log:
            p = serve(arm, rd, log)
            try:
                r = Resp(PORT)
                row = {"arm": arm, **prepare(r, 40_000)}
                r.cmd("CONFIG", "SET", "activedefrag", "yes")
                time.sleep(15)
                row.update(sample(r, p.pid))
                row["passes"] = passes(rd)[:30]
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
                print(json.dumps({k: row.get(k) for k in ("arm", "rep", "frag_ratio_before", "w0_cor_p99_ms",
                                                          "w10_cor_p99_ms", "w45_cor_p99_ms", "w45_effort_mean",
                                                          "w45_main_cpu_frac", "server_peak_rss_mb")}), flush=True)


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
    keys = ["frag_ratio_before", "threshold_upper"]
    for a, _ in WINDOWS:
        keys += [f"w{a}_effort_mean", f"w{a}_raw_p50_ms", f"w{a}_cor_p50_ms", f"w{a}_cor_p99_ms", f"w{a}_raw_max_ms",
                 f"w{a}_raw_over_10ms", f"w{a}_main_cpu_frac"]
    keys += ["hits_end", "misses_end", "frag_ratio_end", "server_cpu_s", "server_peak_rss_mb"]
    out = [f"# redis no-yield-feedback: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"{NKEYS:,} module values of {VSIZE} bytes, every other one deleted (fragmentation the scan cannot move), "
           "defrag on at t=0 for 80 s with a PING every 1 ms. wA_*: the window from A s ([0,10), [10,40), [45,75)); "
           "effort_mean: INFO active_defrag_running (percent of each tick), main_cpu_frac: main-thread CPU per second. "
           "mean, sd [min, max].", ""] + table(rows, keys)
    if os.path.exists(f"{D}/data/check.json"):
        out += ["", "## Decision check (40,000 keys, 20,000 live, 15 s): each arm's pass log", "", "```"]
        for c in json.load(open(f"{D}/data/check.json")):
            out += [f"{c['arm']}:"] + [f"  {x}" for x in c["passes"][:16]]
        out += ["```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"check": check, "measure": lambda: measure(int(a[1])), "report": report}[a[0]]()

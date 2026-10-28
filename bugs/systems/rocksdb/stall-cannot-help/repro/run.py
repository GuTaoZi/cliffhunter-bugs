#!/usr/bin/env python3
"""rocksdb/stall-cannot-help (queue rank 37): write stalls fire with auto compaction off, where nothing can end them.

Bug (db/column_family.cc at e4609a749be4, RecalculateWriteStallConditions, lines 545-620): the L0 file-count and
pending-compaction-bytes stop and slowdown triggers (561-562, 572-574, 597-599, 614-616) apply whether or not auto
compaction is on. With disable_auto_compactions, no compaction is ever picked (db_impl.cc:3342), L0 only grows, so
once L0 reaches level0_slowdown_writes_trigger every later write is throttled to delayed_write_rate, forever, and at
level0_stop_writes_trigger writes stop for good. Fixed upstream in ee027fc19f4a (2016-08-02): each trigger also
requires !disable_auto_compactions. Parent e4609a749be4.

One run: db_bench fillseq of NUM 1,000-byte values (WAL off, no compression, 4 MB memtables, auto compaction off,
L0 slowdown at 6 files, the stop trigger out of reach, delayed_write_rate 1 MB/s), then stats; tmpfs; measured by
tools/reproduce/runcmd.py through tools/reproduce/dbbench.py (per-write latency histogram, throughput per second,
cumulative stall, rocksdb.stall.micros, the LOG's "Stalling writes" lines; wall, CPU, peak RSS). MODE=stop instead
sets the stop trigger to 10 under a 60 s timeout: the parent never finishes. Arms alternate per repetition.

    run.py measure [REPS] [MODE] | report
"""
import json
import os
import statistics as st
import sys

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
sys.path.insert(0, f"{REPO}/tools/reproduce")
from dbbench import run  # noqa: E402

ARMS = {"parent": "e4609a749be4", "fix": "ee027fc19f4a"}
NUM = int(os.environ.get("NUM", 80_000))
ARGS = ["--benchmarks=fillseq,stats", f"--num={NUM}", "--key_size=16", "--value_size=1000", "--compression_type=none",
        "--disable_wal=1", "--write_buffer_size=4194304", "--max_write_buffer_number=3", "--disable_auto_compactions=1",
        "--level0_slowdown_writes_trigger=6", "--delayed_write_rate=1048576", "--histogram=1", "--statistics=1",
        "--report_interval_seconds=1", "--threads=1"]
LOGPAT = {"stalling_l0": r"Stalling writes because we have \d+ level-0 files",
          "stopping_l0": r"Stopping writes because we have \d+ level-0 files"}


def one(arm, rep, mode):
    stop = ["--level0_stop_writes_trigger=10"] if mode == "stop" else ["--level0_stop_writes_trigger=1000000"]
    out = f"{D}/data/{arm}-{mode}-r{rep}.txt"
    rec = run(f"{ROOT}/build/rocksdb-{ARMS[arm]}/src/db_bench", ARGS + stop, out, f"/dev/shm/ch-rdb37-{arm}",
              timeout_s=60 if mode == "stop" else 600, log_patterns=LOGPAT)
    rec.update({"arm": arm, "sha": ARMS[arm], "rep": rep, "mode": mode, "num": NUM})
    return rec


SHOW = ("arm", "mode", "rep", "exit", "wall_s", "fillseq_ops_per_s", "fillseq_p50_us", "fillseq_p99_us", "fillseq_max_us",
        "cum_stall_s", "log_stalling_l0", "cpu_s", "peak_rss_mb")


def measure(reps, mode):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, mode)
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
    keys = ["wall_s", "fillseq_ops_per_s", "fillseq_p50_us", "fillseq_p99_us", "fillseq_p999_us", "fillseq_max_us",
            "fillseq_avg_us", "cum_stall_s", "cum_stall_pct", "stall_micros", "sec_under_5pct", "log_stalling_l0",
            "log_stopping_l0", "cpu_s", "peak_rss_mb"]
    out = [f"# rocksdb stall-cannot-help: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"db_bench fillseq of {rows[0]['num']:,} 1,000-byte values with auto compaction off and an L0 slowdown "
           "trigger of 6 files (delayed_write_rate 1 MB/s), on tmpfs; fillseq_*: db_bench's per-write latency "
           "histogram; cum_stall: its stats benchmark. mean, sd [min, max]."]
    for mode, title in (("delay", "Slowdown (stop trigger out of reach)"), ("stop", "Stop trigger 10, 60 s timeout")):
        sub = [r for r in rows if r["mode"] == mode]
        if sub:
            out += ["", f"## {title}", ""] + table(sub, keys)
            if mode == "stop":
                out += ["", "exit codes (124: killed by the timeout): " + ", ".join(
                    f"{r['arm']} r{r['rep']} {r['exit']}" for r in sub)]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5,
                                sys.argv[3] if len(sys.argv) > 3 else "delay"),
     "report": report}[sys.argv[1]]()

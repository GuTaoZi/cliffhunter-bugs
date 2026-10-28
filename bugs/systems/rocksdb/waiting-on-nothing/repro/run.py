#!/usr/bin/env python3
"""rocksdb/waiting-on-nothing (queue rank 38): a delayed write sleeps its whole computed delay, even once the delay
condition is gone.

Bug (db/db_impl.cc at e66221add4e8, DelayWrite, lines 5131-5147): when the write controller needs a delay, the write
leader computes delay = num_bytes / delayed_write_rate (write_controller.cc:97-104; a 1 MB batch at 1 MB/s is about
1 s), unlocks the DB mutex and sleeps that long in one SleepForMicroseconds call, without re-checking whether the
delay token was released meanwhile (a flush or compaction finishing, column_family.cc:746). Fixed upstream in
d52f334cbd4b (2017-03-16): it sleeps 1 ms at a time while write_controller_.NeedsDelay(), until the computed deadline.
Parent e66221add4e8.

One run (the memtable-count slowdown, chosen to be deterministic; the commit's own workload depends on compaction
speed): db_bench fillseq of NUM 1,000,000-byte values (WAL off, snappy, 10 MB memtables, at most 4, one flush thread,
auto compaction off, delayed_write_rate 1 MB/s), then stats; tmpfs. With 3 memtables waiting for flush the writer is
delayed (column_family.cc:653-659) and the flush ends the condition within tens of ms. Measured by
tools/reproduce/runcmd.py through tools/reproduce/dbbench.py (per-write latency histogram, throughput per second,
cumulative stall, rocksdb.stall.micros, the LOG's "Stalling writes" lines; wall, CPU, peak RSS). Arms alternate per
repetition.

    run.py measure [REPS] | report
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

ARMS = {"parent": "e66221add4e8", "fix": "d52f334cbd4b"}
NUM = int(os.environ.get("NUM", 800))
ARGS = ["--benchmarks=fillseq,stats", f"--num={NUM}", "--key_size=16", "--value_size=1000000",
        "--write_buffer_size=10485760", "--max_write_buffer_number=4", "--max_background_flushes=1",
        "--disable_auto_compactions=1", "--disable_wal=1", "--delayed_write_rate=1000000", "--histogram=1",
        "--statistics=1", "--report_interval_seconds=1", "--threads=1"]
LOGPAT = {"stalling_imm": r"Stalling writes because we have \d+ immutable memtables",
          "stopping_imm": r"Stopping writes because we have \d+ immutable memtables",
          "stalling_l0": r"Stalling writes because we have \d+ level-0 files"}


def one(arm, rep, mode):
    out = f"{D}/data/{arm}-r{rep}.txt"
    rec = run(f"{ROOT}/build/rocksdb-{ARMS[arm]}/src/db_bench", ARGS, out, f"/dev/shm/ch-rdb38-{arm}", timeout_s=900,
              log_patterns=LOGPAT)
    rec.update({"arm": arm, "sha": ARMS[arm], "rep": rep, "mode": mode, "num": NUM})
    return rec


SHOW = ("arm", "mode", "rep", "exit", "wall_s", "fillseq_ops_per_s", "fillseq_p50_us", "fillseq_p99_us", "fillseq_max_us",
        "cum_stall_s", "log_stalling_imm", "cpu_s", "peak_rss_mb")


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
            "fillseq_avg_us", "cum_stall_s", "cum_stall_pct", "stall_micros", "sec_under_5pct", "log_stalling_imm",
            "log_stopping_imm", "log_stalling_l0", "cpu_s", "peak_rss_mb"]
    out = [f"# rocksdb waiting-on-nothing: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"db_bench fillseq of {rows[0]['num']:,} 1,000,000-byte values, 10 MB memtables (at most 4), one flush "
           "thread, auto compaction off, delayed_write_rate 1 MB/s, on tmpfs; fillseq_*: db_bench's per-write latency "
           "histogram; cum_stall: its stats benchmark; log_stalling_imm: the LOG's slowdowns on 3 waiting "
           "memtables. mean, sd [min, max].", ""] + table(rows, keys)
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5, "delay"),
     "report": report}[sys.argv[1]]()

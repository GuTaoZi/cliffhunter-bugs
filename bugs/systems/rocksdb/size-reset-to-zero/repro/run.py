#!/usr/bin/env python3
"""rocksdb/size-reset-to-zero (queue rank 11): automatic readahead never starts after the adaptive-readahead change,
so long scans with direct reads go block by block. Parent 924616526a14 against the fix 04b2c16f9b81 ("Fix bug in
rocksdb internal automatic prefetching", #9234), release builds of db_bench (tools/reproduce/build.sh).

    run.py build          build both arms (run under the machine lock)
    run.py fill           one database for both arms (fillseq with the fix's db_bench; reads do not change it)
    run.py measure [REPS] seekrandom with direct reads, arms alternated per repetition -> data/runs.jsonl
    run.py report         results.md

The workload is the fix's own benchmark, smaller: 2,000,000 keys of 32 B with 512 B values; seekrandom with
use_direct_reads=true, seek_nexts=100,000, no explicit readahead_size, 30 s per run. Measured per run: MB/s and
micros/op from db_bench, wall, user and system CPU and peak RSS from /usr/bin/time, and the prefetch tickers.
"""
import json
import os
import re
import statistics as st
import subprocess
import sys

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../.."))
ARMS = {"parent": "924616526a14", "fix": "04b2c16f9b81"}
DB = f"{D}/db"
COMMON = ["-key_size=32", "-value_size=512", "-num=2000000"]
READ = ["-use_existing_db=true", "-benchmarks=seekrandom", "-use_direct_reads=true", "-seek_nexts=100000",
        "-duration=30", "-ops_between_duration_checks=1", "-statistics=true", "-threads=1"]


def bench(arm):
    return f"{ROOT}/build/rocksdb-{ARMS[arm]}/src/db_bench"


def build():
    for arm, sha in ARMS.items():
        r = subprocess.run(["sh", f"{REPO}/tools/reproduce/build.sh", "rocksdb", sha], capture_output=True, text=True)
        print(arm, sha, "rc", r.returncode, r.stdout.strip().split("\n")[-1][:120])


def fill():
    subprocess.run(["rm", "-rf", DB])
    r = subprocess.run([bench("fix"), f"-db={DB}", "-benchmarks=fillseq", *COMMON, "-disable_wal=true"],
                       capture_output=True, text=True)
    print(r.stdout[-400:], r.stderr[-400:])
    subprocess.run([bench("fix"), f"-db={DB}", "-use_existing_db=true", "-benchmarks=compact", *COMMON],
                   capture_output=True, text=True)


def one(arm, rep):
    cmd = ["/usr/bin/env", "time", "-f", "TIME %e %U %S %M", bench(arm), f"-db={DB}", *COMMON, *READ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    m = re.search(r"seekrandom\s*:\s*([\d.]+) micros/op\s+(\d+) ops/sec;\s+([\d.]+) MB/s", out)
    t = re.search(r"TIME ([\d.]+) ([\d.]+) ([\d.]+) (\d+)", out)
    tick = {k: int(v) for k, v in re.findall(r"rocksdb\.(prefetch\.\S+|file\.read\.\S*bytes\S*) COUNT : (\d+)", out)}
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "rc": r.returncode,
           "micros_per_op": float(m.group(1)) if m else None, "ops_per_s": int(m.group(2)) if m else None,
           "mb_per_s": float(m.group(3)) if m else None,
           "wall_s": float(t.group(1)) if t else None, "user_s": float(t.group(2)) if t else None,
           "sys_s": float(t.group(3)) if t else None, "peak_rss_mb": int(t.group(4)) / 1024 if t else None,
           "tickers": tick}
    if not m:
        row["tail"] = out[-600:]
    return row


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            order = ["parent", "fix"] if rep % 2 else ["fix", "parent"]
            for arm in order:
                row = one(arm, rep)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in ("arm", "rep", "mb_per_s", "micros_per_op", "user_s", "sys_s",
                                                      "peak_rss_mb")}))


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["mb_per_s", "micros_per_op", "ops_per_s", "wall_s", "user_s", "sys_s", "peak_rss_mb"]
    out = ["# rocksdb size-reset-to-zero: parent 924616526a14 vs fix 04b2c16f9b81", "",
           "seekrandom, use_direct_reads=true, seek_nexts=100,000, 2,000,000 keys (32 B + 512 B), 30 s per run; "
           "mean, sd [min, max] over repetitions.", "", "| metric | parent | fix | fix / parent |", "|---|---|---|---|"]
    for k in keys:
        cells = []
        means = {}
        for arm in ("parent", "fix"):
            v = [r[k] for r in rows if r["arm"] == arm and r[k] is not None]
            means[arm] = st.mean(v) if v else None
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})" if v else "-")
        ratio = f"{means['fix'] / means['parent']:.2f}" if means["parent"] and means["fix"] else "-"
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "fill":
        fill()
    elif cmd == "measure":
        measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif cmd == "report":
        report()

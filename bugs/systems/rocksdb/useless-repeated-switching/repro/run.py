#!/usr/bin/env python3
"""rocksdb/useless-repeated-switching: buggy parent vs fix, WriteBufferManager flushes.

Bug (db/db_impl/db_impl_write.cc): when the shared WriteBufferManager says memtable memory is over
its limit, the write path switches a column family's memtable to immutable so it gets flushed. It
could pick the same busy CF again and again, switching nearly empty memtables, which frees no
memory and soon hits max_write_buffer_number, so writes stall. Fixed by 91166012c848 (2022-08-17),
which skips CFs that already have an immutable memtable waiting for flush.

Each run is the commit's own test plan: db_bench fillrandom with 8 DBs x 2 CFs sharing a 16 MB
write-buffer budget, on tmpfs, measured with tools/reproduce/runcmd.py. It records the rocksdb.db.write.stall
histogram (in this version it records every pass through the write-delay check, so its COUNT is
not a count of stalls; its P99 and max are kept) and stall.micros from -statistics, throughput, and
from the DBs' LOG files: the flushes and their memtable sizes, and how often writes were stopped or
slowed because the immutable-memtable limit was reached. Arms alternate; buggy is repeated last. Each run's DB directory is removed afterwards.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
ARMS = {"buggy": f"{ROOT}/build/rocksdb-65814a4ae646/src/db_bench",
        "fixed": f"{ROOT}/build/rocksdb-91166012c848/src/db_bench"}
ARGS = ["-benchmarks=fillrandom", "-num_multi_db=8", "-num_column_families=2", "-write_buffer_size=4194304",
        "-db_write_buffer_size=16777216", "-compression_type=none", "-statistics=true",
        "-target_file_size_base=4194304", "-max_bytes_for_level_base=16777216"]
SHM = "/dev/shm/cliffhunter-bugs"


def one(arm, rep):
    tmp = os.path.join(SHM, f"{arm}-{rep}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    out = os.path.join(REPO, "data", "experiments", "rocksdb-useless-repeated-switching", "raw", f"{arm}-{rep}.txt")
    env = dict(os.environ, TEST_TMPDIR=tmp)
    m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "runcmd.py"), out, "--", ARMS[arm], *ARGS],
                       capture_output=True, text=True, env=env)
    rec = json.loads(m.stdout)
    rec.update(parse(open(out).read()))
    rec.update(parse_logs(glob.glob(os.path.join(tmp, "**", "LOG"), recursive=True)))
    shutil.rmtree(tmp)
    rec.update({"arm": arm, "rep": rep})
    return rec


def parse_logs(logs):
    """Flushes and their memtable sizes, and write stops/slowdowns, from the DBs' info LOGs."""
    sizes, stops, slows = [], 0, 0
    for log in logs:
        txt = open(log, errors="replace").read()
        sizes += [int(x) for x in re.findall(r'"event": "flush_started".*?"total_data_size": (\d+)', txt)]
        stops += len(re.findall(r"Stopping writes because we have \d+ immutable memtables", txt))
        slows += len(re.findall(r"Stalling writes because we have \d+ immutable memtables", txt))
    sizes.sort()
    return {"flushes": len(sizes), "flush_mb_median": sizes[len(sizes) // 2] / 2**20 if sizes else None,
            "flush_mb_total": sum(sizes) / 2**20,
            "flushes_under_256kb": sum(1 for x in sizes if x < 256 * 1024),
            "stops_on_immutable_limit": stops, "slowdowns_on_immutable_limit": slows,
            "log_files": len(logs)}


def parse(txt):
    def num(pat):
        m = re.search(pat, txt)
        return float(m.group(1)) if m else None
    return {"ops_per_s": num(r"fillrandom\s*:\s*[\d.]+ micros/op (\d+) ops/sec"),
            "write_stall_count": num(r"rocksdb\.db\.write\.stall P50 : [\d.]+ P95 : [\d.]+ P99 : [\d.]+ "
                                     r"P100 : [\d.]+ COUNT : (\d+)"),
            "stall_micros": num(r"rocksdb\.stall\.micros COUNT : (\d+)"),
            "write_stall_p99_us": num(r"rocksdb\.db\.write\.stall P50 : [\d.]+ P95 : [\d.]+ P99 : ([\d.]+)"),
            "write_stall_max_us": num(r"rocksdb\.db\.write\.stall P50 : [\d.]+ P95 : [\d.]+ P99 : [\d.]+ "
                                      r"P100 : ([\d.]+)")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "rocksdb-useless-repeated-switching", "raw"), exist_ok=True)
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "rocksdb-useless-repeated-switching", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, rep)
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, {k: rec[k] for k in ("ops_per_s", "stall_micros", "write_stall_p99_us", "flushes",
                                                 "flush_mb_median", "flushes_under_256kb",
                                                 "stops_on_immutable_limit", "slowdowns_on_immutable_limit",
                                                 "wall_s", "cpu_s", "peak_rss_mb")}, flush=True)


if __name__ == "__main__":
    main()

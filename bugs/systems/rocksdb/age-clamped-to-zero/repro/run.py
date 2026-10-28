#!/usr/bin/env python3
"""rocksdb/age-clamped-to-zero (queue rank 36): block-cache entry stats are recollected on every call.

Bug (cache/cache_entry_stats.h at 80a59a03a7d6, GetStats, lines 55-74): max_age_micros =
static_cast<uint64_t>(std::min(maximum_age_in_seconds, 0)) * 1000000U is 0 for any non-negative age (60-61), so
(start - last_end) > max_age_micros always holds (70) and every call scans the whole block cache
(ApplyToAllEntries, 74). The stats are collected under the DB mutex for each column family: by GetProperty /
GetMapProperty("rocksdb.block-cache-entry-stats") (db_impl.cc:3200, 3227) and by DumpStats, which holds mutex_ across
all column families (db_impl.cc:922-930), one scan each, while every write leader needs mutex_
(db_impl_write.cc:219). Fixed upstream in 2f93a3b80912 (2021-06-08, "Fix a major performance bug in 6.21 for cache
entry stats"): std::max(maximum_age_in_seconds, 1), so a collection is reused for 180 s. Parent 80a59a03a7d6.

One run (workload A of the design: the periodic stats dump): db_bench fillseq, flush, readrandom, overwrite, stats
with 64 column families sharing one 1 GB LRU block cache, 256-byte blocks, no compression, WAL off,
stats_dump_period_sec 1, on tmpfs. flush writes every column family's memtable to a table file (1,200,000 keys are
about 2 MB per column family, under the 8 MB memtable: without it, as in a first version kept in
data/first-version-no-flush/, every read is served from memtables and the cache holds one entry), readrandom fills
the cache with data blocks, and overwrite then writes while the dumps run. Measured by tools/reproduce/runcmd.py through tools/reproduce/dbbench.py: each benchmark's throughput and
per-op latency histogram, throughput per second; wall, CPU, peak RSS. From the LOG: the block-cache stats lines and
the largest "collections:" count (how many times the cache was scanned). Arms alternate per repetition.

    run.py measure [REPS] | report
"""
import json
import os
import re
import statistics as st
import sys

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
sys.path.insert(0, f"{REPO}/tools/reproduce")
from dbbench import run  # noqa: E402

ARMS = {"parent": "80a59a03a7d6", "fix": "2f93a3b80912"}
NUM = int(os.environ.get("NUM", 1_200_000))
CFS = int(os.environ.get("CFS", 64))
ARGS = ["--benchmarks=fillseq,flush,readrandom,overwrite,stats", f"--num_column_families={CFS}", f"--num={NUM}",
        "--reads=3000000", "--key_size=16", "--value_size=100", "--compression_type=none", "--block_size=256",
        "--cache_size=1073741824", "--write_buffer_size=8388608", "--disable_wal=1", "--threads=1",
        "--stats_dump_period_sec=1", "--histogram=1", "--statistics=1", "--report_interval_seconds=1"]
LOGPAT = {"cache_stats_lines": r"Block cache \S+ capacity", "stats_dumps": r"------- DUMPING STATS -------"}


def one(arm, rep, mode):
    out = f"{D}/data/{arm}-r{rep}.txt"
    rec = run(f"{ROOT}/build/rocksdb-{ARMS[arm]}/src/db_bench", ARGS, out, f"/dev/shm/ch-rdb36-{arm}", timeout_s=1800,
              log_patterns=LOGPAT)
    log = out[:-4] + "-LOG"
    if os.path.exists(log):
        c = [int(x) for x in re.findall(r"collections: (\d+)", open(log, errors="replace").read())]
        rec["collections_max"] = max(c) if c else None
    rec.update({"arm": arm, "sha": ARMS[arm], "rep": rep, "mode": mode, "num": NUM, "cfs": CFS})
    return rec


SHOW = ("arm", "rep", "exit", "wall_s", "overwrite_ops_per_s", "overwrite_p99_us", "overwrite_p9999_us", "overwrite_max_us",
        "readrandom_ops_per_s", "log_stats_dumps", "collections_max", "cpu_s", "peak_rss_mb")


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
    keys = ["overwrite_ops_per_s", "overwrite_p50_us", "overwrite_p99_us", "overwrite_p999_us", "overwrite_p9999_us",
            "overwrite_max_us", "overwrite_avg_us", "readrandom_ops_per_s", "readrandom_p99_us", "readrandom_max_us",
            "fillseq_ops_per_s", "sec_ops_p5", "sec_ops_p50", "sec_under_5pct", "sec_under_5pct_longest",
            "log_stats_dumps", "log_cache_stats_lines", "collections_max", "wall_s", "cpu_s", "peak_rss_mb"]
    out = [f"# rocksdb age-clamped-to-zero: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"db_bench fillseq, flush, readrandom, overwrite, stats: {rows[0]['cfs']} column families sharing a 1 GB block "
           f"cache, {rows[0]['num']:,} keys, 256-byte blocks, stats dumped every second, on tmpfs. overwrite_*: per-write "
           "latency while the dumps run; collections_max: the LOG's count of block-cache scans; sec_*: per-second "
           "throughput over the whole run. mean, sd [min, max].", ""] + table(rows, keys)
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5, "delay"),
     "report": report}[sys.argv[1]]()

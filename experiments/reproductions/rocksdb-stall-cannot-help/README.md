# P31 rocksdb-stall-cannot-help — write stalls with auto compaction off, which nothing can end

Queue rank 37 of `bugs/tables/queue.tsv` (severity 3.5, relevance 5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/rocksdb/stall-cannot-help/repro/`; raw data: `data/experiments/rocksdb-stall-cannot-help/raw/`.

**The bug.** RocksDB's `RecalculateWriteStallConditions` (`db/column_family.cc` at e4609a749be4, lines 545-620) slows or stops writes on the L0 file count and on pending compaction bytes (561-562, 572-574, 597-599, 614-616) whether or not auto compaction is on. With `disable_auto_compactions`, no compaction is ever picked (`db/db_impl.cc:3342`), so L0 only grows: once it reaches `level0_slowdown_writes_trigger`, every later write is throttled to `delayed_write_rate` for good, and at `level0_stop_writes_trigger` writes stop and never resume (`DelayWrite`'s wait, `db_impl.cc:4856-4860`). The stall cannot help, because nothing it waits for will happen. Fixed upstream in ee027fc19f4a (2016-08-02, "Ignore write stall triggers when auto-compaction is disabled"): each trigger also requires `!disable_auto_compactions`.

**Arms.** Parent e4609a749be4 against the fix ee027fc19f4a, release builds (`tools/reproduce/build.sh`: GCC 15.3, `-O2`, no assertions; the 2016 tree builds with `-include functional` added, which changes no program code). Each run on a fresh DB in tmpfs, measured by `tools/reproduce/runcmd.py` (wall, CPU, peak RSS) through `tools/reproduce/dbbench.py`. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload.** `db_bench --benchmarks=fillseq,stats --num=80000 --value_size=1000 --compression_type=none --disable_wal=1 --write_buffer_size=4194304 --max_write_buffer_number=3 --disable_auto_compactions=1 --level0_slowdown_writes_trigger=6 --level0_stop_writes_trigger=1000000 --delayed_write_rate=1048576 --histogram=1 --statistics=1`: a bulk load with compaction off, the case `disable_auto_compactions` exists for. A second variant sets the stop trigger to 10, under a 60 s timeout.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| loading 80,000 values with auto compaction off | parent | fix | parent / fix |
|---|---|---|---|
| wall time | 41.3 s (sd 1.5) | 0.127 s | 326 |
| throughput | 1,940 writes/s | 790,800 writes/s | 0.002 |
| p99 write latency | 1,196 µs | 1.8 µs | 648 |
| p99.9 write latency | 1,200 µs | 4.9 µs | 243 |
| mean write latency | 516 µs | 1.3 µs | 407 |
| cumulative stall (`stats`) | 41.2 s, 99.7% of the run | 0.046 s | 895 |
| LOG "Stalling writes because we have N level-0 files" | 24.4 | 0 | |
| CPU | 0.55 s | 0.18 s | 3.1 |
| peak RSS | 21.7 MB | 21.9 MB | 1.0 |
| stop trigger 10 (n=1) | killed at the 60 s timeout, never finishes | 0.125 s | |

After the sixth flush the parent delays every write by about 1 ms (the 1 MB/s token bucket for a 1 KB write) until the end of the load, with no compaction that could ever lift the condition; with the stop trigger in reach it hangs for good. The fix's maximum write latency (about 10 ms in both arms) is a memtable switch, the same in both. The bug is in latency, and at the stop trigger in availability.

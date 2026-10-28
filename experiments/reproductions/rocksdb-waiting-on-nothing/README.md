# P32 rocksdb-waiting-on-nothing — a delayed write sleeps its whole delay after the cause is gone

Queue rank 38 of `bugs/tables/queue.tsv` (severity 3.5, relevance 5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/rocksdb/waiting-on-nothing/repro/`; raw data: `data/experiments/rocksdb-waiting-on-nothing/raw/`.

**The bug.** When RocksDB's write controller asks for a delay, the write leader computes it once, `delay = num_bytes / delayed_write_rate` (`db/write_controller.cc` at e66221add4e8, lines 97-104: a 1 MB batch at 1 MB/s is about 1 s), unlocks the DB mutex and sleeps that long in one `SleepForMicroseconds` call (`DelayWrite`, `db/db_impl.cc:5131-5147`). It never re-checks the condition: when a flush or compaction finishes and releases the delay token (`db/column_family.cc:746`) a few milliseconds in, the writer keeps sleeping for the rest of the second. Fixed upstream in d52f334cbd4b (2017-03-16, "Break stalls when no bg work is happening"): it sleeps 1 ms at a time while `write_controller_.NeedsDelay()`, up to the computed deadline.

**Arms.** Parent e66221add4e8 against the fix d52f334cbd4b, release builds (`tools/reproduce/build.sh`: GCC 15.3, `-O2`, no assertions; the 2017 trees build with `-include functional -include array -include sys/sysmacros.h` added, which changes no program code). Each run on a fresh DB in tmpfs, measured by `tools/reproduce/runcmd.py` (wall, CPU, peak RSS) through `tools/reproduce/dbbench.py`. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (deterministic: the memtable-count slowdown; the commit's own workload depends on compaction speed). `db_bench --benchmarks=fillseq,stats --num=800 --value_size=1000000 --write_buffer_size=10485760 --max_write_buffer_number=4 --max_background_flushes=1 --disable_auto_compactions=1 --disable_wal=1 --delayed_write_rate=1000000 --histogram=1 --statistics=1` (snappy). The writer fills 10 MB memtables faster than one thread flushes them; with three waiting for flush the writer is delayed (`column_family.cc:653-659`), and a flush ends the condition within tens of milliseconds.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| loading 800 values of 1 MB | parent | fix | parent / fix |
|---|---|---|---|
| p99 write latency | 1,001,000 µs (sd 9) | 22,760 µs | 44 |
| maximum write latency | 1,001,000 µs | 23,250 µs | 43 |
| median write latency | 360 µs | 355 µs | 1.0 |
| wall time | 24.4 s (sd 2.3) | 0.99 s | 24.6 |
| cumulative stall (`stats`) | 24.0 s, 98% of the run | 0.66 s | 36 |
| LOG "Stalling writes because we have 3 immutable memtables" | 24.2 | 52 | |
| CPU | 1.82 s | 1.27 s | 1.43 |
| peak RSS | 47.6 MB | 48.6 MB | 1.0 |

In the parent each slowdown costs one write exactly the computed second (p99 and maximum are both 1.001 s in every run), about 24 times per run; in the fix the same condition arises more often (52 times, as more writes arrive per second) but each delayed write waits only until the flush finishes (about 23 ms). The bug is in latency.

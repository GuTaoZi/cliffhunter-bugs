# P37 rocksdb-age-clamped-to-zero — block-cache stats recollected on every call under the DB mutex

Queue rank 36 of `bugs/tables/queue.tsv` (severity 4, relevance 4.5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/rocksdb/age-clamped-to-zero/repro/`; raw data: `data/experiments/rocksdb-age-clamped-to-zero/raw/`.

**The bug.** RocksDB collects block-cache entry statistics (`rocksdb.block-cache-entry-stats`, and the periodic stats dump) by scanning the whole block cache, and is meant to reuse a collection for up to 180 s. At 80a59a03a7d6, `GetStats` (`cache/cache_entry_stats.h`, lines 55-74) computes the reuse age as `static_cast<uint64_t>(std::min(maximum_age_in_seconds, 0)) * 1000000U`, which is 0 for any non-negative age (60-61). So `(start - last_end) > max_age_micros` always holds (70), and every call scans the cache again (`ApplyToAllEntries`, 74). The collection runs once per column family under the DB mutex: from `GetProperty` and `GetMapProperty` (`db/db_impl/db_impl.cc:3200`, `3227`), and from `DumpStats`, which holds `mutex_` across all column families (`db_impl.cc:922-930`). Every write leader needs that mutex (`db/db_impl/db_impl_write.cc:219`). Fixed upstream in 2f93a3b80912 (2021-06-08, "Fix a major performance bug in 6.21 for cache entry stats"): `std::max(maximum_age_in_seconds, 1)`, so a collection is reused.

**Arms.** Parent 80a59a03a7d6 against the fix 2f93a3b80912. Release builds from `tools/reproduce/build.sh`: GCC 15.3, `-O2`, no assertions. Each run used a fresh DB in tmpfs, measured by `tools/reproduce/runcmd.py` (wall, CPU, peak RSS) through `tools/reproduce/dbbench.py`. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (the periodic stats dump, the design's workload A). `db_bench --benchmarks=fillseq,flush,readrandom,overwrite,stats --num_column_families=64 --num=1200000 --reads=3000000 --value_size=100 --compression_type=none --block_size=256 --cache_size=1073741824 --write_buffer_size=8388608 --disable_wal=1 --stats_dump_period_sec=1 --histogram=1 --statistics=1`.
- The 64 column families share one 1 GB LRU block cache.
- `flush` writes each memtable to a table file, and `readrandom` then fills the cache with data blocks.
- `overwrite` measures the writes while the dumps run, once a second.

A first version without `flush` is kept in `data/first-version-no-flush/`. There, 1,200,000 keys come to about 2 MB per column family, under the 8 MB memtable, so every read was served from a memtable. The cache held one entry, a scan took 98 µs, and writes showed no difference.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| overwriting 1,200,000 keys while the stats are dumped every second | parent | fix | parent / fix |
|---|---|---|---|
| longest write | 6.44 s (sd 0.17) | 10.2 ms | 631 |
| overwrite throughput | 128,200 writes/s | 737,100 writes/s | 0.17 |
| mean write latency | 7.8 µs | 1.36 µs | 5.8 |
| median and p99.99 write latency | 0.76 µs, 9.6 µs | 0.75 µs, 9.1 µs | 1.0 |
| block-cache scans (LOG `collections:`) | 532 | 1 | |
| wall time of the run | 17.3 s | 9.0 s | 1.9 |
| CPU | 21.8 s | 9.1 s | 2.4 |
| peak RSS | 468.5 MB | 468.9 MB | 1.0 |

The LOG gives the mechanism's numbers. One scan of the filled cache takes 47 ms (`last_secs: 0.047`), and a dump runs about 133 of them, one per column family per statistic, with the DB mutex held: 6.3 s per dump, exactly the parent's longest write (6.26-6.71 s in the five runs). While a dump runs, every writer waits, and per-second throughput drops to zero. With the fix, the cache is scanned once and the other dumps copy that collection. The write percentiles hide the stall, because a few writes absorb it all: median and p99.99 are equal in both arms, while the maximum is 631 times higher. The bug is in latency: writes stop for over six seconds at each stats dump.

The raw directory keeps each run's db_bench output, per-second throughput and DB LOG (gzip-compressed, `*-LOG.gz`).

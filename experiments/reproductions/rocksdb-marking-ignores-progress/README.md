# P26 rocksdb-marking-ignores-progress — preserve_internal_time_seconds: an endless bottommost-files compaction loop

Queue rank 8 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). Reproduced on 2026-10-27 in the main session; the report follows. Code: `bugs/systems/rocksdb/marking-ignores-progress/repro/`; raw data: `data/experiments/rocksdb-marking-ignores-progress/raw/` (not copied, too large: librocksdb-00d697bdc532.a (a build output), librocksdb-6dbb6f30e604.a (a build output), librocksdb-eca47fb6960e.a (a build output), librocksdb-f7b791b213b2.a (a build output); they stay in the data root's repro/ directory).

Queue rank 8 of `bugs/tables/queue.tsv` (severity 4, relevance 5, cost low; two raters). Reproduced on 2026-10-27 in the main session with the driver of P24 (`bottom_loop.cc`, `rank8c.sh`); two earlier setups did not reproduce it and are kept (`rank8b.sh`, results `r8-*` and `r8b-*`).

**The bug.** Leveled compaction with `preserve_internal_time_seconds` (or `preclude_last_level_data_seconds`): a bottommost file whose largest sequence number is still inside the preserve window cannot have its sequence numbers zeroed, yet it was marked for bottommost compaction (`kBottommostFiles`) once the oldest snapshot passed it. Each rewrite made no progress and the output was re-marked at once: an endless compaction loop that rewrites the file and grows the MANIFEST. Fixed upstream in f7b791b21 (#15146, 2026-08-26): marking and compaction output share one predicate, `BottommostSeqnoCanBeZeroed`, fed with the preserve-window boundary.

**Arms.** Parent 6dbb6f30e604 against the fix f7b791b213b2, release builds (`tools/reproduce/build.sh`, `DEBUG_LEVEL=0`, -O2); the driver linked against each arm's objects with `-fno-rtti`, C++20 from the commit's own make_config.mk, and the `unique_ptr` form of `DB::Open` these commits use (`link.sh`, `link8.sh`). Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (the fix's unit test `LeveledPreserveTimeNoBottommostLoop`, with a real clock and more data): level compaction, 7 levels, `preserve_internal_time_seconds=100` (so RocksDB records its sequence-number-to-time mapping about every second); 100,000 keys of 1,000 B written twice over 20 s; flushed and moved to the last level (6); one more key written and flushed; a snapshot taken and released. Then 30 s with no requests, measured as for P24.

**What did not reproduce it.** The same steps with the file moved only to L1 (`preserve_internal_time_seconds=10000`, writes within a second; then 100 with writes over 20 s) gave 2 ordinary compactions in both arms: the loop needs the file on the last level, as in the test.

**Results** (mean, sd over 5 runs per arm; `results-rank8.md`):

| over the 30 s idle window | parent | fix |
|---|---|---|
| compactions (all `kBottommostFiles`) | 429 (sd 2.9) | 0 |
| bytes rewritten by compaction | 986 MB (sd 6.8) | 0 |
| process CPU | 26.8 s (sd 0.06), 89% of a core | 0.001 s |
| MANIFEST size | 940 B to 53 KB | 940 B |
| peak RSS | 24.6 MB | 21.3 MB |

An idle database rewrites its bottommost file 14 times a second for as long as the data stays inside the preserve window (here 100 s; with the production-scale windows this option is meant for, hours or days), and the MANIFEST grows with every rewrite. The fix leaves it idle.

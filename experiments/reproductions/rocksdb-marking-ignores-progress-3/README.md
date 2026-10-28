# P24 rocksdb-marking-ignores-progress-3 — allow_ingest_behind: an endless bottommost-files compaction loop

Queue rank 9 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). Reproduced on 2026-10-27 in the main session; the report follows. Code: `bugs/systems/rocksdb/marking-ignores-progress-3/repro/`; raw data: `data/experiments/rocksdb-marking-ignores-progress-3/raw/` (not copied, too large: librocksdb-00d697bdc532.a (a build output), librocksdb-6dbb6f30e604.a (a build output), librocksdb-eca47fb6960e.a (a build output), librocksdb-f7b791b213b2.a (a build output); they stay in the data root's repro/ directory).

Queue rank 9 of `bugs/tables/queue.tsv` (severity 4, relevance 5, cost low; two raters). Reproduced on 2026-10-27 in the main session (`bottom_loop.cc`, `session.sh`, `campaign.sh`; the same driver serves rank 8, which this setup did not reproduce).

**The bug.** RocksDB marks a bottommost file for compaction (reason `kBottommostFiles`) once the oldest snapshot has passed its largest sequence number, so that compaction can zero the sequence numbers. With `allow_ingest_behind=true` the last level is reserved for ingestion and sequence numbers are never zeroed, so the rewritten file is marked again at once: an endless compaction loop. Fixed upstream in eca47fb69 (#10767, 2022): skip bottommost-files marking under `allow_ingest_behind` (issue #10752).

**Arms.** Parent 00d697bdc532 against the fix eca47fb6960e, release builds (`tools/reproduce/build.sh`, `DEBUG_LEVEL=0`, -O2); the driver linked against each arm's objects with the same flags plus `-fno-rtti` (`link.sh`). Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (the fix's unit test, larger): level compaction, `allow_ingest_behind=true`; 100,000 keys of 1,000 B written twice (overwritten versions), flushed and moved to L1; one more key written and flushed; a snapshot taken and released. Then 30 s with no requests, measured: compactions completed by reason (an `EventListener`), bytes written by compaction, process CPU, peak RSS, MANIFEST size.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| over the 30 s idle window | parent | fix |
|---|---|---|
| compactions (all `kBottommostFiles`) | 218 (sd 3.4) | 0 |
| bytes rewritten by compaction | 1,376 MB (sd 22) | 0 |
| process CPU | 21.2 s (sd 0.2), 71% of a core | 0 |
| MANIFEST size after | 28 KB (from 881 B) | 881 B |
| peak RSS | 20.1 MB | 16.7 MB |

With no requests at all, the parent rewrites its 6 MB bottommost file about 7 times a second, indefinitely, and the MANIFEST grows with every rewrite; the fix does nothing. The cost is CPU and write I/O (46 MB/s of compaction output) on an idle database.

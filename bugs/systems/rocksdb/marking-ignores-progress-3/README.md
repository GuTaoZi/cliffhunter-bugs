# rocksdb/marking-ignores-progress-3

Reproduced, a fixed bug (parent vs fix): with allow_ingest_behind the bottommost file is re-marked after every rewrite; an idle database runs 218 compactions per 30 s, rewriting 1.38 GB with 21.2 s CPU (71% of a core) and growing the MANIFEST from 881 B to 28 KB, vs nothing with the fix

- **Upstream:** fixed upstream in eca47fb69
- **Effect:** cpu, strong: an idle database runs 218 compactions per 30 s (1.38 GB rewritten, 21.2 s CPU, 71% of a core; MANIFEST 881 B to 28 KB) vs none
- **Experiment:** P24, report: [experiments/reproductions/rocksdb-marking-ignores-progress-3/README.md](../../../../experiments/reproductions/rocksdb-marking-ignores-progress-3/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); host make and ar; GNU time on PATH; about 7 GB of disk

**Build:**

```sh
sh bugs/systems/rocksdb/marking-ignores-progress-3/repro/session.sh
sh bugs/systems/rocksdb/marking-ignores-progress-3/repro/link8.sh
```

**Run:**

```sh
sh bugs/systems/rocksdb/marking-ignores-progress-3/repro/campaign.sh
python3 bugs/systems/rocksdb/marking-ignores-progress-3/repro/aggregate.py
```

**Writes:** repro/results/r9-*.json (this bug) and r8-*.json, repro/results.md, the drivers and librocksdb-<sha12>.a in repro/

**Minutes:** about 19 (four builds; 20 runs of 31 s)

**Notes:** session.sh builds parent 00d697bdc532 and fix eca47fb6960e and links their drivers; it also builds the sibling bug's pair (6dbb6f30e604, f7b791b213b2), whose link there fails as recorded, hence link8.sh before campaign.sh. The result is the r9 half of results.md; its r8 half is the sibling bug's first setup, which did not reproduce.

## The report

Copied from [`experiments/reproductions/rocksdb-marking-ignores-progress-3/README.md`](../../../../experiments/reproductions/rocksdb-marking-ignores-progress-3/README.md).

### P24 rocksdb-marking-ignores-progress-3 — allow_ingest_behind: an endless bottommost-files compaction loop

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

## Files

- [`repro/aggregate.py`](repro/aggregate.py)
- [`repro/bottom_loop.cc`](repro/bottom_loop.cc)
- [`repro/campaign.sh`](repro/campaign.sh)
- [`repro/link.sh`](repro/link.sh)
- [`repro/link8.sh`](repro/link8.sh)
- [`repro/session.sh`](repro/session.sh)

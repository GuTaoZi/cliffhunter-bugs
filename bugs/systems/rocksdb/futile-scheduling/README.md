# rocksdb/futile-scheduling

Reproduced, a fixed bug (parent vs fix): with auto compactions disabled every snapshot release schedules a compaction that does nothing; 219, 423 and 2,274 futile jobs per 20 s at 0, 100 and 1,000 marked column families vs 0 with the fix; the cost is small (compaction pool 0.36 s CPU per 20 s, ReleaseSnapshot 2.3x slower at 1,000; put latency unchanged)

- **Upstream:** fixed upstream in 416943bf2
- **Effect:** cpu, small: 219 / 423 / 2,274 no-op compactions per 20 s (0 / 100 / 1,000 marked column families) vs 0; compaction pool 0.36 s CPU per 20 s and ReleaseSnapshot 2.3x at 1,000; put latency unchanged
- **Experiment:** P22, report: [experiments/reproductions/rocksdb-futile-scheduling/README.md](../../../../experiments/reproductions/rocksdb-futile-scheduling/README.md)

## Run it

Paths are relative to the kit's root; `tools/reproduce/setup.sh` first (see the top README).

**Needs:** Nix; host make and ar; about 1 GB of disk in the repro directory and 5 free cores

**Build:**

```sh
tools/reproduce/build.sh rocksdb b7e1c5213f00
tools/reproduce/build.sh rocksdb 416943bf28b4
sh bugs/systems/rocksdb/futile-scheduling/repro/link_driver.sh b7e1c5213f00
sh bugs/systems/rocksdb/futile-scheduling/repro/link_driver.sh 416943bf28b4
```

**Run:**

```sh
sh bugs/systems/rocksdb/futile-scheduling/repro/session2.sh
python3 bugs/systems/rocksdb/futile-scheduling/repro/aggregate.py main2 > bugs/systems/rocksdb/futile-scheduling/repro/results.md
```

**Writes:** repro/results/main2-*.{json,out,err,LOG.gz}, repro/results.md, the drivers futile_driver-<sha12> and librocksdb-<sha12>.a in repro/

**Minutes:** about 22

**Notes:** link_driver.sh links futile_driver.cc against the build's object files (keep the build directory as built). Without the drivers every run fails with 'no driver output'. The k1000 case opens over 1,000 files: raise ulimit -n if it is 1024. go.sh, go_build.sh, session1.sh, build_arm.sh and smoke2.sh are earlier steps, not part of the final run.

## The report

Copied from [`experiments/reproductions/rocksdb-futile-scheduling/README.md`](../../../../experiments/reproductions/rocksdb-futile-scheduling/README.md).

### P22 rocksdb-futile-scheduling — snapshot releases schedule no-op compactions when auto compactions are off

Queue rank 7 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). The driver was written by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`) on 2026-10-22; the builds, runs and this report were done in the main session on 2026-10-27. Code: `bugs/systems/rocksdb/futile-scheduling/repro/`; raw data: `data/experiments/rocksdb-futile-scheduling/raw/` (not copied: librocksdb-416943bf28b4.a and librocksdb-b7e1c5213f00.a, build outputs, and src-parent/, an export of upstream source; they stay in the data root's repro/ directory).

Queue rank 7 of `bugs/tables/queue.tsv` (severity 4, relevance 5, cost low; two raters). A reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`) wrote the driver on 2026-10-22 and stopped at a session limit before any run (both builds had failed under GCC 15: 2020 RocksDB's bundled folly uses `std::system_error` without its header). Built, linked and measured on 2026-10-27 in the main session: `tools/reproduce/build.sh` now force-includes `<system_error>` for RocksDB, and the driver is compiled with `-fno-rtti` like the release library it subclasses.

**The bug.** After a snapshot is released, RocksDB checks `ColumnFamilyData::NeedsCompaction()` to schedule bottommost-file compaction. With `disable_auto_compactions=true` that check still returned true, so every release scheduled a compaction job that did nothing ("Compaction nothing to do"), left the trigger set, and was scheduled again at the next release. Fixed upstream in 416943bf2 (#7267, 2020): `NeedsCompaction()` returns false when auto compactions are disabled. The upstream message reports high CPU and DB-mutex contention.

**Arms.** Parent b7e1c5213f00 against the fix 416943bf28b4, release builds (`DEBUG_LEVEL=0`, -O2, flags in each build's `flags.txt`); `futile_driver.cc` linked against each arm's objects. Arms interleaved, order alternated per round, 5 rounds, under the machine lock (`session2.sh`, `campaign.sh`).

**Workload** (`futile_driver.cc`): all column families with auto compactions disabled; a paced writer (20,000 put/delete pairs per second, 1 KB values) makes every flushed file a bottommost file with deletions; two threads loop GetSnapshot/ReleaseSnapshot (20,000 per second each); optional "cold" column families each hold one marked bottommost file (0, 100 or 1,000). 20 s measured per run; per-operation latency, per-thread-group CPU, peak RSS, LOW-priority jobs scheduled, and the LOG's "nothing to do" lines.

**Results** (mean over 5 runs per arm; full tables in `results.md`):

| cold column families | futile compactions scheduled, parent / fix | compaction-pool CPU, parent / fix | ReleaseSnapshot mean, parent / fix | process CPU, parent / fix | put p99, parent / fix |
|---|---|---|---|---|---|
| 0 | 219 / 0 | 0.059 / 0 s | 0.26 / 0.51 us | 6.84 / 7.55 s | 16.8 / 19.5 us |
| 100 | 423 / 0 | 0.073 / 0 s | 0.15 / 0.18 us | 6.98 / 7.20 s | 19.7 / 18.9 us |
| 1,000 | 2,274 / 0 | 0.358 / 0 s | 0.41 / 0.18 us | 7.49 / 6.45 s | 18.6 / 17.4 us |

Every parent job is a futile one (scheduled = "nothing to do" lines); the fix schedules none. The cost grows with the number of marked column families but stays small here: at 1,000 the compaction pool spends 0.36 s per 20 s, ReleaseSnapshot is 2.3x slower on average and process CPU 1.16x (the fix's runs vary, sd 1.3 s); foreground put latency is unchanged and no DB-mutex wait was recorded. Reproduced; the mechanism is exact, the cost on this machine small.

## Files

- [`repro/aggregate.py`](repro/aggregate.py)
- [`repro/build_arm.sh`](repro/build_arm.sh)
- [`repro/campaign.sh`](repro/campaign.sh)
- [`repro/futile_driver.cc`](repro/futile_driver.cc)
- [`repro/go.sh`](repro/go.sh)
- [`repro/go_build.sh`](repro/go_build.sh)
- [`repro/link_driver.sh`](repro/link_driver.sh)
- [`repro/run_one.sh`](repro/run_one.sh)
- [`repro/session1.sh`](repro/session1.sh)
- [`repro/session2.sh`](repro/session2.sh)
- [`repro/smoke2.sh`](repro/smoke2.sh)
- [`repro/summarize_run.py`](repro/summarize_run.py)

# rocksdb/masked-second-trigger

Reproduced, a fixed bug (parent vs fix): the write-buffer flush check never runs while total WAL size is over its limit; peak RSS 2,627 vs 364 MB, memtables 2,589 vs 347 MB, 0 vs 92 memory flushes; the fix throttles writes (7 vs 31 MB/s, Put mean 135 vs 15 us)

- **Upstream:** fixed upstream in 18eeb7b90e45
- **Effect:** memory, strong: peak RSS 2,627 vs 364 MB; the fix throttles writes, so the buggy version is faster
- **Experiment:** P18, report: [experiments/reproductions/rocksdb-masked-second-trigger/README.md](../../../../experiments/reproductions/rocksdb-masked-second-trigger/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); host make and ar; about 4 GB of free RAM and 4-6 GB of disk

**Build:**

```sh
tools/reproduce/build.sh rocksdb 1560b2f5f014
tools/reproduce/build.sh rocksdb 18eeb7b90e45
```

**Run:**

```sh
sh bugs/systems/rocksdb/masked-second-trigger/repro/go.sh
python3 bugs/systems/rocksdb/masked-second-trigger/repro/aggregate.py main
python3 bugs/systems/rocksdb/masked-second-trigger/repro/aggregate.py long
```

**Writes:** repro/results/{main,long}-{parent,fix}-*.{json,csv,LOG,out,err}, the drivers wbm_driver-<sha12> and librocksdb-<sha12>.a in repro/; aggregate.py prints its tables

**Minutes:** about 18

**Notes:** go.sh links both drivers, runs a 4 s smoke run, then 3 pairs of 90 s and one pair of 180 s. Absolute numbers depend on the disk: the recorded disk was rotational, with flushes at 3.4-4.1 MB/s; the trigger needs paced writes (32 MiB/s) faster than flushes.

## The report

Copied from [`experiments/reproductions/rocksdb-masked-second-trigger/README.md`](../../../../experiments/reproductions/rocksdb-masked-second-trigger/README.md).

### P18 rocksdb-masked-second-trigger — the memory flush check is masked by the WAL check

Queue rank 3 of `bugs/tables/queue.tsv` (severity 4.5, relevance 5, two raters). Reproduced on 2026-10-22 by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`); its report follows, as returned. Code: `bugs/systems/rocksdb/masked-second-trigger/repro/`; raw data: `data/experiments/rocksdb-masked-second-trigger/raw/` (not copied, too large: Makefile.parent (a build output), db_bench_tool.cc.parent (a build output), db_impl.cc.parent (a build output), librocksdb-1560b2f5f014.a (a build output), librocksdb-18eeb7b90e45.a (a build output); they stay in the data root's repro/ directory).

Runs took place 2026-10-22, 22:14:33 to 22:30:55 EDT, all inside one machine-lock acquisition.

#### Verdict
**Confirmed.** At the fix's parent, the `db_write_buffer_size` check never runs while the total WAL size stays over `max_total_wal_size`. It fired 0 times in all 4 parent runs, against 83 to 133 times at the fix. Peak RSS was 2627 ± 77 MB at the parent against 364 ± 35 MB at the fix, 7.2 times higher and far above the run-to-run spread. The fix pays for this: its writes are throttled to the flush rate.

#### Arms
| arm | commit | build dir | flags (flags.txt) |
|---|---|---|---|
| buggy (fix's parent) | 1560b2f5f014 | $CLIFF_DATA/build/rocksdb-1560b2f5f014 | GCC 15.3.0, `-O2 -DNDEBUG` (DEBUG_LEVEL=0), `-std=c++11`, PORTABLE (`-march=x86-64 -mtune=generic`), assert_warning_in_db_bench=0 |
| fixed | 18eeb7b90e45 | $CLIFF_DATA/build/rocksdb-18eeb7b90e45 | identical |

- Both arms were built with `tools/reproduce/build.sh rocksdb COMMIT` under flock.
- `diff -r` of the two exported trees: only `db/db_impl.cc` differs, at the fix's two lines.
- db_bench cannot sample memtable properties during a run, so the workload is a driver of its own, `wbm_driver.cc`.
  - `link_driver.sh` links it against each arm's own release objects (that build's LIB_SOURCES `.o` files, archived into `librocksdb-SHA.a`).
  - It is compiled with the same `-O2 -DNDEBUG -std=c++11` and platform defines; the flags are recorded in `wbm_driver-SHA.flags`.
- The database runs in-process, so the driver process is the "server":
  - CPU is getrusage(RUSAGE_SELF) over the run, counting writer, flush and sampler threads.
  - Peak memory is VmHWM; VmRSS is also sampled every 100 ms.

#### Workload
- **Writes:** 20 column families. One writer thread puts 16-byte keys and 1000-byte random values into random column families, paced at 32 MiB/s. WAL on, no sync.
- **Settings:** `max_total_wal_size`=32 MiB, `db_write_buffer_size`=64 MiB, `write_buffer_size`=64 MiB, `max_write_buffer_number`=4, auto compactions off, no compression, 1 flush thread.
- **Flush bottleneck:** a rate limiter of 8 MiB/s applies to flush writes only; WAL files have IO_TOTAL priority and are not limited (util/file_reader_writer.cc:310@1560b2f5f014).
  - The disk (sda) is rotational, so the effective flush rate was 3.4 to 4.1 MB/s in both arms (SST bytes created ÷ 90 s, from the LOGs).
  - Writes therefore outrun flushes, which is the claimed trigger.
- **Sampling:** every 100 ms the driver records `rocksdb.cur-size-all-mem-tables`, `rocksdb.cur-size-active-mem-table` and `num-immutable-mem-table` (summed over column families) plus VmRSS, to `results/TAG.csv`.
- **Campaign:** 3 repetitions per arm, 90 s each, interleaved P F F P P F. Then one 180 s run per arm.
- **Command:** `flock $CLIFF_DATA/locks/machine.lock go.sh`
  - go.sh relinks both drivers, runs a 4 s smoke test, then `campaign.sh main 3 90` and `campaign.sh long 1 180`.
  - One run on its own: `run_one.sh SHA12 TAG --seconds=90 --cfs=20 --write_rate=33554432 --flush_rate=8388608 --db_write_buffer_size=67108864 --write_buffer_size=67108864 --max_write_buffer_number=4 --max_total_wal_size=33554432 --value_size=1000`

#### Results: main campaign, 90 s, n=3 per arm (mean (sd) [min-max])
| metric | parent 1560b2f5f014 (buggy) | fix 18eeb7b90e45 |
|---|---|---|
| write rate achieved, MB/s | 31.25 (0.33) [30.93-31.59] | 6.97 (0.55) [6.33-7.30] |
| Put latency mean, µs | 15.3 (1.2) [13.9-16.2] | 134.5 (12) [127.3-147.8] |
| Put latency p50 / p99, µs (bucket lower bound) | 10.2 / 20.5 | 8.9 / 1049 |
| Put latency max, ms | 1542 (810) [839-2429] | 34470 (5000) [28890-38360] |
| CPU, s (process, 90 s) | 40.64 (0.23) [40.38-40.80] | 9.62 (1.1) [8.61-10.86] |
| CPU per Put, µs | 14.00 (0.11) | 14.44 (1.1) |
| **peak RSS, MB** | **2627 (77) [2564-2713]** | **364 (35) [325-390]** |
| **peak cur-size-all-mem-tables, MB** | **2589 (89) [2534-2691]** | **347 (29) [315-371]** |
| **peak active memtables, MB** (limit 64) | **1233 (1.6)** | **64.3 (0.06)** |
| memtables at 30 / 60 / 90 s, MB | 872 / 1722 / 2563 | 274 / 196 / 332 |
| share of samples with active ≥ db_write_buffer_size | 0.897 | 0.016 |
| **memory-branch flushes** (LOG "Flushing column family with largest mem table size") | **0 (0)** | **91.7 (7.5) [83-96]** |
| WAL-branch flushes that did work | 2 | 5.3 |
| "Stopping writes" / "Stalling writes" | 0 / 3.3 | 8.7 / 28.7 |
| stall time (rocksdb.stall.micros), s | 3.3 (1.8) | 79.6 (3.2) |
| data written, MB | 2812 | 645 |

#### Results: long runs, 180 s, n=1 per arm
| metric | parent | fix |
|---|---|---|
| write rate, MB/s | 20.45 | 5.41 |
| Put latency mean / max | 35.8 µs / 27.7 s | 176 µs / 41.8 s |
| CPU, s / CPU per Put, µs | 60.2 / 14.8 | 16.8 / 16.7 |
| peak RSS, MB | 3415 | 440 |
| peak memtables, MB | 3387 | 393 |
| peak active memtables, MB | 1229 | 64.3 |
| memory-branch flushes | 0 | 133 |
| stops / slowdowns | 2 / 15 | 21 / 55 |

- **Parent memtables over time (MB):** 455 at 15 s, 882 at 30 s, 1752 at 60 s, 2499 at 90 s, 2984 at 120 s, 3191 at 150 s, 3256 at 165 s. From 165 s writes stop entirely, because column families reach 4 immutable memtables of 64 MB each.
- **Fix memtables over time:** they move between 136 and 375 MB for the whole 180 s.

#### Mechanism
- **The masking (`db/db_impl.cc:4737-4740@1560b2f5f014`):** `if (!single_column_family_mode_ && total_log_size_ > GetMaxTotalWalSize()) MaybeFlushColumnFamilies(); else if (write_buffer_manager_->ShouldFlush()) {switch largest active memtable}`. The memory check runs only when the WAL check is false.
- **The WAL branch does nothing (`db/db_impl.cc:5061-5063@1560b2f5f014`):** `MaybeFlushColumnFamilies()` returns at once when the oldest live WAL is already `getting_flushed`.
- **The WAL check stays true (`db/db_impl.cc:895-911@1560b2f5f014`):** `total_log_size_` shrinks only when the oldest WAL is released, which requires every column family with data in it to have flushed. With flushes behind writes, that takes a long time.
- **What the logs show:** each parent run logged only 2 WAL-branch flushes, and the memory branch fired 0 times. Yet active memtables were at or over 64 MB in 90-95% of samples.
- **What limits memory instead:** only the per-column-family `write_buffer_size`, giving 20 × ~61.6 MB = 1.23 GB of active memtables.
  - Each column family has only a few large immutables, so the memtable-count stall rule fires late (`db/column_family.cc:629@1560b2f5f014`: stop at ≥ max_write_buffer_number; `:661-662`: slow down at ≥ max−1).
  - The real cap is num_cfs × max_write_buffer_number × write_buffer_size (5 GB here), which grows with the number of column families, not with db_write_buffer_size.
  - This matches the commit message: memtables "way above db_write_buffer_size and keeps growing".
- **The fix (`db/db_impl.cc:4737-4741@18eeb7b90e45`):** the memory check becomes a separate `if (write_buffer_manager_->ShouldFlush())`.
  - It switches the largest active memtable whenever active bytes reach 64 MB, so active memtables stay at 64.3 MB.
  - The many small immutables hit the stop and slowdown rules early (8.7 stops against 0). That throttles the writer to the flush rate and holds total memtables near 0.35 GB.

#### What did not work, and caveats
- **The fix does not cap total memtables at db_write_buffer_size.** At this commit `ShouldFlush()` counts only mutable memtables: `MemTable::MarkImmutable()` (db/memtable.h:313-315) calls `DoneAllocating()` (db/memtable_allocator.cc:45-49), which frees the memtable's reservation, and `ShouldFlush()` is `memory_usage() >= buffer_size()` (include/rocksdb/write_buffer_manager.h:38-40), all @1560b2f5f014. At the fix, total memtables still reached 5-6 times the limit (347 MB against 64 MB); the bound comes indirectly from the stall rule. "Grows without bound" at the parent means without the db_write_buffer_size bound.
- **The fix costs throughput and tail latency.**
  - Write rate is 4.5 times lower.
  - Put max latency is 29-42 s, from "Stopping writes" while a stopped column family waits its turn in the single flush queue.
  - 80 of 90 s are spent stalled.
  - CPU per Put is the same in both arms (14.0 against 14.4 µs); total CPU is lower at the fix only because fewer Puts complete.
- **Flush speed:** the bottleneck is the rotational disk plus the limiter. The effective flush rate was 3-4 MB/s rather than 8 MiB/s, the same in both arms.
- **Latency percentiles** come from a log2 histogram with 4 sub-buckets and report the bucket's lower bound, hence the repeated 10.24 / 20.48 / 1048.6 µs values. Mean and max are exact.
- **The first 8 s smoke tests** (`results/smoke-parent.*`, `results/smoke-fix.*`) used an earlier driver without the active-memtable column. They showed almost no difference (228 against 217 MB), because the fix's backpressure takes about 10 s to build; hence the 90 s and 180 s runs.
- No ports or servers were used (the database is in-process), no repository changes, no network. No database directories or processes are left behind.

#### Files
The driver and scripts (`wbm_driver.cc`, `link_driver.sh`, `build_arm.sh`, `go.sh`, `campaign.sh`, `run_one.sh`, `summarize_run.py`, `aggregate.py`) are in the bug's `repro/` directory. Per-run data (`results/`), logs and the driver flags are in the raw-data directory. The linked binaries and the two 170 MB static libraries were not copied; `link_driver.sh` rebuilds them from the release builds.

## Files

- [`repro/aggregate.py`](repro/aggregate.py)
- [`repro/build_arm.sh`](repro/build_arm.sh)
- [`repro/campaign.sh`](repro/campaign.sh)
- [`repro/go.sh`](repro/go.sh)
- [`repro/link_driver.sh`](repro/link_driver.sh)
- [`repro/run_one.sh`](repro/run_one.sh)
- [`repro/summarize_run.py`](repro/summarize_run.py)
- [`repro/wbm_driver.cc`](repro/wbm_driver.cc)

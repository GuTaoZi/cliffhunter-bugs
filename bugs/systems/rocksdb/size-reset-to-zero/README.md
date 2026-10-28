# rocksdb/size-reset-to-zero

Reproduced, a fixed bug (parent vs fix): automatic readahead never starts, so long scans with direct reads go block by block; seekrandom 188.5 vs 250.8 MB/s (272 vs 204 ms per 100,000-entry scan, 1.33x), system CPU 3.3x; peak RSS equal

- **Upstream:** fixed upstream in 04b2c16f9
- **Effect:** latency, moderate: scan throughput 188.5 vs 250.8 MB/s (272 vs 204 ms per 100,000-entry scan, 1.33x), system CPU 3.3x
- **Experiment:** P23, report: [experiments/reproductions/rocksdb-size-reset-to-zero/README.md](../../../../experiments/reproductions/rocksdb-size-reset-to-zero/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); GNU time on PATH; a filesystem with O_DIRECT (not tmpfs) and 0.6 GB in the repro directory

**Build:**

```sh
tools/reproduce/build.sh rocksdb 924616526a14
tools/reproduce/build.sh rocksdb 04b2c16f9b81
```

**Run:**

```sh
python3 bugs/systems/rocksdb/size-reset-to-zero/repro/run.py fill
python3 bugs/systems/rocksdb/size-reset-to-zero/repro/run.py measure 5
python3 bugs/systems/rocksdb/size-reset-to-zero/repro/run.py report
```

**Writes:** repro/db/ (about 576 MB), repro/data/runs.jsonl (appended), repro/results.md

**Minutes:** about 7

**Notes:** Both arms read one database written by the fix's db_bench. Delete data/runs.jsonl before a re-run. The ratio depends on the storage (1.33x on this machine's SSD; the upstream report saw 12x on other storage with a debug build).

## The report

Copied from [`experiments/reproductions/rocksdb-size-reset-to-zero/README.md`](../../../../experiments/reproductions/rocksdb-size-reset-to-zero/README.md).

### P23 rocksdb-size-reset-to-zero — automatic readahead never starts after the adaptive-readahead change

Queue rank 11 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). Reproduced on 2026-10-27 in the main session; the report follows. Code: `bugs/systems/rocksdb/size-reset-to-zero/repro/`; raw data: `data/experiments/rocksdb-size-reset-to-zero/raw/` (not copied, too large: db/ (576 MB); they stay in the data root's repro/ directory).

Queue rank 11 of `bugs/tables/queue.tsv` (severity 4, relevance 5, cost low; two raters). Reproduced on 2026-10-27 in the main session (`run.py`, `session.sh`).

**The bug.** RocksDB starts automatic readahead for a block-based table iterator after it sees sequential reads, and grows it while the scan continues (`BlockPrefetcher`, `FilePrefetchBuffer`). After the adaptive-readahead change, the initial readahead size was 0, so automatic prefetching never started: a long scan with direct reads fetches block by block. Fixed upstream in 04b2c16f9 (#9234, 2021): a nonzero initial readahead size again. The fix's message reports seekrandom at 29.4 MB/s before and 359.8 MB/s after, with `use_direct_reads=true` and `seek_nexts=327680`, on a debug build (assertions enabled).

**Arms.** Parent 924616526a14 against the fix 04b2c16f9b81, release builds of `db_bench` (`tools/reproduce/build.sh`: `DEBUG_LEVEL=0`, -O2, flags in each build's `flags.txt`). One database for both arms (2,000,000 keys of 32 B with 512 B values, `fillseq` then `compact`, written by the fix's `db_bench`; the benchmark only reads it). Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload.** The fix's own benchmark, smaller: `db_bench -use_existing_db=true -benchmarks=seekrandom -use_direct_reads=true -seek_nexts=100000 -duration=30 -ops_between_duration_checks=1 -threads=1`, no explicit readahead size. Per run: db_bench's MB/s and micros/op, and wall, user, system CPU and peak RSS from `/usr/bin/time`.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| metric | parent | fix | fix / parent |
|---|---|---|---|
| scan throughput | 188.5 MB/s (sd 11) | 250.8 MB/s (sd 9.7) | 1.33 |
| time per scan of 100,000 entries | 272 ms (sd 17) | 204 ms (sd 8) | 0.75 |
| system CPU per 30 s run | 1.03 s | 0.31 s | 0.31 |
| user CPU per 30 s run | 11.2 s | 20.9 s | 1.86 (more data processed) |
| peak RSS | 27.8 MB | 27.5 MB | 0.99 |

The parent is 1.33x slower on every run (no overlap between arms) and spends 3.3x the system CPU on its many small direct reads; the fix reads ahead and spends its CPU processing more data. The upstream 12x was measured on a debug build and another machine's storage; on this machine's storage with release builds the loss is a third of the scan throughput.

## Files

- [`repro/run.py`](repro/run.py)
- [`repro/session.sh`](repro/session.sh)

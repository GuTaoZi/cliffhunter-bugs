# rocksdb/useless-repeated-switching

Useless repeated switching (parent of 91166012c848 vs the fix): write stops 283-317 vs 0, stall 1.81x, throughput unchanged (0.987x): partly negative

- **Upstream:** fixed upstream in 91166012c (<https://github.com/facebook/rocksdb/commit/91166012c> <https://github.com/facebook/rocksdb/pull/6364>)
- **Effect:** latency, weak: 283-317 vs 0 write stops, stall time 1.81x, throughput unchanged
- **Experiment:** P7, report: [experiments/reproductions/rocksdb-useless-repeated-switching/README.md](../../../../experiments/reproductions/rocksdb-useless-repeated-switching/README.md)

## Run it

Paths are relative to the kit's root; `tools/reproduce/setup.sh` first (see the top README).

**Needs:** Nix; a tmpfs at /dev/shm with room for 8 small databases (1-2 GB)

**Build:**

```sh
tools/reproduce/build.sh rocksdb 65814a4ae646
tools/reproduce/build.sh rocksdb 91166012c848
```

**Run:**

```sh
python3 bugs/systems/rocksdb/useless-repeated-switching/repro/run.py
python3 tools/reproduce/summarize.py experiments/reproductions/rocksdb-useless-repeated-switching > experiments/reproductions/rocksdb-useless-repeated-switching/summary.json
```

**Writes:** data/experiments/rocksdb-useless-repeated-switching/raw/{buggy,fixed}-*.txt and runs.jsonl (replaced), the summary.json

**Minutes:** about 5

**Notes:** The useful fields are stops_on_immutable_limit (from the databases' LOG files), stall_micros and the write-stall latency; rocksdb.db.write.stall COUNT is not a stall count in this version. Measured on 48 cores with tmpfs.

## The report

Copied from [`experiments/reproductions/rocksdb-useless-repeated-switching/README.md`](../../../../experiments/reproductions/rocksdb-useless-repeated-switching/README.md).

### P7 rocksdb/useless-repeated-switching — reproduced: about 290 write stops per run vanish; throughput unchanged

**Bug.** When the shared `WriteBufferManager` reports memtable memory over its limit, the write
path switches one column family's memtable to immutable so that it gets flushed
(`db/db_impl/db_impl_write.cc`). It could pick the same busy CF again and again. Switching its
nearly empty memtable frees almost no memory and soon reaches `max_write_buffer_number`, and then
writes stop. Fixed by 91166012c848 (2022-08-17), which skips CFs that already have an immutable
memtable waiting for flush.

**Builds:**

| arm | commit |
|---|---|
| buggy | 65814a4ae646, the parent of the fix |
| fixed | 91166012c848 |

Both are `DEBUG_LEVEL=0`, `-O2`, NDEBUG (`flags.txt`).

**Workload** (`run.py`, the commit's test plan): `db_bench -benchmarks=fillrandom -num_multi_db=8
-num_column_families=2`, with 4 MB write buffers and a 16 MB shared budget. The data is 8,000,000
writes, on tmpfs. There are 5 interleaved repetitions plus a drift run. The commit's metric, the
`rocksdb.db.write.stall` COUNT, does not count stalls in this version. It counts every pass
through the write-delay check (262 to 584,216 across our runs), so we use other measures. Those
are the write stops logged in each DB's `LOG` ("Stopping writes because we have N immutable
memtables"), `rocksdb.stall.micros`, and the stall histogram's P99 and maximum.

#### Result (`summary.json`, `raw/runs.jsonl`)

| arm | runs | write stops on the immutable limit | total stall | P99 / max write stall | ops/s | CPU | peak RSS |
|---|---|---|---|---|---|---|---|
| buggy | 6 | **283–317** | 2.60 s | 13.8 ms / 30.3 ms | 521,900 | 32.0 s | 46.0 MB |
| fixed | 5 | **0** | 1.45 s | 1 µs / 1.4 ms | 528,400 | 33.2 s | 48.8 MB |

The fix removes the stops it targets. Total stall time falls 1.81× (95% CI 1.64–1.98) and the
worst stall 22×. **End-to-end throughput does not change** (0.987×, CI 0.97–1.01), and the buggy
arm uses slightly *less* CPU (0.964×, CI 0.93–1.00).

The flush counts explain this. Both arms flush the same 955 MB in total. The fixed arm does it
in 2,764 flushes (median memtable 0.26 MB, 1,416 under 256 KB). The buggy arm uses 1,821 flushes
(median 0.44 MB, 291 under 256 KB). Skipping the busy CF sends the switch to *other* CFs, whose
memtables are even smaller. The fix therefore turns write stops into more, smaller flushes. On
this 48-core machine with tmpfs, those flushes are cheap. **The latency effect is confirmed.
Wasted switching is not reduced; it moves to other CFs.**

## Files

- [`repro/run.py`](repro/run.py)

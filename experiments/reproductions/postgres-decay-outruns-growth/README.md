# P41 postgres-decay-outruns-growth — read-stream look-ahead decays per hit faster than it grows

Queue rank 20 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/postgres/decay-outruns-growth/repro/`; raw data: `data/experiments/postgres-decay-outruns-growth/raw/`.

**The bug.** A PostgreSQL read stream (`src/backend/storage/aio/read_stream.c` at cceb1bf45e3a) adapts its look-ahead distance in two ways:
- It doubles the distance only after waiting for a read (952-955).
- It drops the distance by one for every buffer hit that needed no I/O (365-370).

A scan whose uncached blocks are separated by cached ones therefore falls back to distance 1 or 2 between misses. At most one read is in flight, and every miss is waited for at once, at the device's queue-depth-1 latency, whatever `effective_io_concurrency` says. Fixed upstream in 6e36930f9aaf (2026-04-01): after each wait, decay is held off for `max_pinned_buffers` hits (`distance_decay_holdoff`, 366-384, 984), and it never decays while reads are in flight.

**Arms.** Parent cceb1bf45e3a against the fix 6e36930f9aaf, release builds from `tools/reproduce/build.sh` (GCC 15.3, `-O2`). The fix changes no catalog version, so both arms run on one data directory, on the machine's ext4 disk (a hardware RAID virtual disk), not tmpfs. Settings in both: `shared_buffers=16GB`, `io_method=worker`, `io_workers=16`, `effective_io_concurrency` 16 (the default) or 64, `autovacuum=off`, no parallel workers, `jit=off`, `synchronize_seqscans=off`. Port 15453. Arms alternated per repetition, 3 repetitions per setting, under the machine lock.

**The device first** (`calibrate_stride`: 8 kB reads from a 1 GB file with its page cache dropped):

| one read every | queue depth 1 | queue depth 16 |
|---|---|---|
| 2 blocks | 0.103 ms | 0.105 ms |
| 16 blocks | 0.79 ms | 0.62 ms |
| 64 blocks | 3.21 ms | 1.16 ms |

The read-ahead of this disk, its controller or the kernel serves a near-sequential pattern as fast one read at a time as sixteen at once. A first version, with every second block uncached (data kept in `data/first-version-stride-2/`), showed no difference: 2.38 vs 2.36 s, and its all-cold control 2.22 vs 2.27 s. The look-ahead can only matter where the misses are far apart, so the table here has one uncached block in every 64.

**Workload.** Table `t(id, m, pad)` with one row per 8 kB block (a 5,000-byte uncompressed pad), block = id, m = id % 64, an index on m, frozen; 320,000 blocks, 2.6 GB. Each run:
1. The table's files are fsynced and dropped from the page cache (`POSIX_FADV_DONTNEED`, checked with `fincore`), and the arm's server starts.
2. The blocks with m > 0 are read into shared buffers (a bitmap heap scan), and the page cache is dropped again. Now 63 blocks in every 64 are buffer hits and the 64th a device read (0 pages resident before the scan, every run).
3. Measured: one `EXPLAIN (ANALYZE, BUFFERS)` sequential scan of the whole table, its wall time, and the server's CPU (postmaster and all children, io workers included) and peak RSS.

In every run of both arms the scan reported `shared hit=315000 read=5000`. The control, `allcold`, skips step 2, so every block is a read and the distance grows in both arms.

**Results** (mean, sd [min, max]; `results.md`):

| one scan: 315,000 hits, 5,000 device reads | parent | fix | parent / fix |
|---|---|---|---|
| scan time, effective_io_concurrency 16 | 23.0 s (sd 1.2) [22.0, 24.6] | 11.2 s (sd 0.1) [11.1, 11.3] | 2.05 |
| per device read | 4.60 ms | 2.24 ms | 2.05 |
| server CPU | 15.0 s | 8.0 s | 1.88 |
| scan time, effective_io_concurrency 64 | 24.3 s (sd 2.2) [22.2, 27.4] | 9.9 s (sd 2.0) [8.3, 12.7] | 2.46 |
| per device read | 4.86 ms | 1.98 ms | 2.46 |
| server CPU | 14.6 s | 5.8 s | 2.52 |
| peak RSS (shared buffers touched) | 2,576 MB | 2,574 MB | 1.0 |
| control, all 320,000 blocks read (n=1) | 21.3 s | 24.9 s | 0.86 |

The parent's scan pays 4.4-5.5 ms per device read, this disk's queue-depth-1 cost for a scattered read plus the 63 hits around it, and raising `effective_io_concurrency` from 16 to 64 does nothing for it (23.0 → 24.3 s). The fix overlaps the reads: 2.24 ms each at the default setting, where its look-ahead window of 272 blocks spans about four misses, and 1.98 ms at 64, where the window spans sixteen. The control shows both arms read at the same speed when nothing is cached. The parent also used about twice the server CPU over its longer scan; where that time goes was not profiled. The bug is in latency: the same query takes twice as long, on any disk whose scattered reads gain from depth.

## Summary

- **gave-up-advising-early**: latency reproduction likely. Cold `VACUUM` over a table with dense runs separated by skipped gaps should be about 1.3-2.2x slower on the parent. Two controls should show no difference.
- **waiter-count-oscillates**: doubtful on this host. The reported penalty is XFS-specific and this host has only ext4. A smaller, different gain from fewer extensions may still show. Design plus a decisive pre-check below.

Nothing was run. I only read code and host state.

**Host facts that shape both designs**
- Only filesystem is ext4 on `/dev/sda3`, a hardware-RAID virtual disk with rotational=1. `read_ahead_kb` is 2048, there are 125 GB of RAM and 99 GB of page cache, and drop_caches is not permitted.
- `/proc/filesystems` has no xfs.
- `strace` exists (`/run/current-system/sw/bin/strace`). ptrace_scope is 1, so only children of the tracer can be traced.
- The earlier design `bugs/systems/postgres/decay-outruns-growth/repro/run.py` measured this device: 3.2 ms per random 8 kB read at queue depth 1 with a 64-block stride, versus 0.1 ms at a 2-block stride. Reuse its `drop_cache` (fsync + `posix_fadvise(DONTNEED)`), `resident_pages` (`fincore`), `Sampler` and ABBA-alternation patterns.
- Default build flags are fine for both arms: `--without-readline --without-icu --without-zlib`, `-O2`.

---

# Item 1: postgres/gave-up-advising-early

## fix and parent
- **Fix:** `7ea8cd15661e`, 2025-03-15, "Improve read_stream.c advice for dense streams." It changes only `src/backend/storage/aio/read_stream.c`.
- **Parent:** `11bd8318602f`, 2025-03-14, "doc: Explain more thoroughly when a table rewrite is needed".
- Same catalog version, so both arms run on one data directory.
- This is before AIO, so there is no `io_method` GUC. Do not pass it.

## the decision
It decides whether a started read gets `READ_BUFFERS_ISSUE_ADVICE`, which becomes `posix_fadvise(WILLNEED)` and starts the kernel I/O early. The stream keeps three things: `seq_blocknum`, the end of the last read that needed a wait; `distance`; and the pending read. A read is "sequential" if `pending_read_blocknum == seq_blocknum`.

At the parent, `src/backend/storage/aio/read_stream.c@11bd8318602f`:
- Lines 269-272: advice only if `!suppress_advice && advice_enabled && pending_read_blocknum != seq_blocknum`. So only the first io_combine_limit-sized read (16 blocks, 128 kB) after a jump is advised. Later chunks of the same dense run get no advice and are read by a synchronous `preadv()` when the consumer arrives.
- Line 334: `seq_blocknum` is updated per started read.
- Lines 796 and 902: `read_stream_look_ahead(stream, true / false)`.
- Lines 835-855: an advised wait doubles `distance`. An unadvised wait decays it by 1 above io_combine_limit, otherwise doubles it up to 16.

The fix, `read_stream.c@7ea8cd15661e`:
- Removes `suppress_advice`.
- Adds `seq_until_processed`. A jump sets it to the new region's start (line 287) and advises if `pinned_buffers > 0` (288-289).
- Sequential reads stay advised while `seq_until_processed != InvalidBlockNumber` (277-278).
- It is cleared when the consumer's wait reaches the I/O whose `op.blocknum == seq_until_processed` (879-881).
- The look-ahead window spans several runs, so advice stays on for essentially every chunk in the window.

Caller used in this design, at the parent:
- `src/backend/access/heap/vacuumlazy.c:1229`: `read_stream_begin_relation(READ_STREAM_MAINTENANCE, ...)`. The callback is `heap_vac_scan_next_block` (1557).
- `SKIP_PAGES_THRESHOLD` is 32 (209, 1609). VACUUM jumps only over all-visible/all-frozen gaps of at least 32 blocks. Its streams are therefore dense runs separated by jumps.
- `src/backend/storage/buffer/freelist.c:663-671`: default 2 MB ring = 256 buffers, pin limit 128. So `max_pinned_buffers` is 128 and the look-ahead window is 8 chunks.

Defaults at the parent: `maintenance_io_concurrency=10`, `io_combine_limit=16`.

## does it show in latency?
**Yes (probable), on cold-cache scans.**

Reasoning: at steady state `distance` saturates at 128 in both arms, because each advised jump wait doubles it and each unadvised chunk only decrements by 1. The parent advises only chunk A of each run. Chunks B and C are read synchronously later, after the head has moved on to other runs' advised chunks. That costs an extra positioning per run, plus kernel read-ahead overshoot into the gap. The overshoot is about 512 kB, from the async window triggered at chunk C. The fix advises A, B and C together and the device queue merges them.

The size depends on the device. A rotational RAID rewards this. If the controller cache hides it, the ratio will be near 1.1. A pre-check below tells you before building anything.

## trigger
- A VACUUM (not aggressive, no indexes) over a table whose non-all-visible pages form dense runs of 48 blocks (3 chunks), separated by at least 2 MB of all-frozen pages.
- Cold page cache and cold shared buffers.
- Runs of exactly 16 blocks are the control. They give a single advised chunk per run in both arms, so the arms are identical.

## workload
**Builds:** `tools/reproduce/build.sh postgres 11bd8318602f` and `... 7ea8cd15661e`.

**Server, same for both arms and every table:**
- Data dir `$ROOT/pgdata/gave-up-advising-early/data`, port 15471. `pg.py` adds `fsync=off` and `listen_addresses=''`.
- Extra options: `-c shared_buffers=512MB -c max_connections=20 -c max_prepared_transactions=8 -c autovacuum=off -c track_io_timing=on -c checkpoint_timeout=1h -c max_wal_size=32GB`.

**Table layout:** one row per 8 kB block, using the 5,000-byte plain pad from the earlier design. N = 400,000 blocks (3.3 GB) per table. Tables:
- `t48`: primary.
- `t16`: control.
- `t96`: optional, runs of 6 chunks.

**Setup (once, with the parent binary):**
```
CREATE TABLE t48(id int, pad text);
ALTER TABLE t48 ALTER COLUMN pad SET STORAGE PLAIN;
INSERT INTO t48 SELECT g, repeat('x',5000) FROM generate_series(0,399999) g;
```
Do the same for `t16` (and `t96`). Then:
```
VACUUM (FREEZE) t48;   -- and the others
CHECKPOINT;
```
- Assert `pg_relation_size('t48') = 400000*8192` and `ctid` of `id=399999` is `(399999,1)`.

**Make the runs non-skippable and idempotent.** Delete inside a prepared transaction so VACUUM can never prune or set the pages all-visible. The scan is then read-only and repeatable on a pristine data dir:
```
BEGIN;
DELETE FROM t48 WHERE id % 400 < 48;
DELETE FROM t16 WHERE id % 400 < 16;
DELETE FROM t96 WHERE id % 400 < 96;
PREPARE TRANSACTION 'hold';
```
- Then `CHECKPOINT`, clean stop, `sync -f <datadir>`.
- The prepared transaction survives restarts. Check `SELECT count(*) FROM pg_prepared_xacts` = 1 at every start.
- Do not put the last 352 blocks in a run. The last block is always scanned, and it must be live.
- Expected scanned pages: 48,001 for `t48` (12.0%), 16,001 for `t16`, 96,001 for `t96`.

**One repetition (arm, table):**
1. Stop the server. For every segment of the table's main fork, plus its `_vm` and `_fsm`, run fsync then `posix_fadvise(DONTNEED)`. Check `fincore` shows 0 resident pages.
2. Start the arm's binary. Run `psql -c "SELECT count(*) FROM pg_class"` to warm catalogs.
3. Snapshot `/sys/block/sda/stat` (sectors read) and `SELECT reads, read_bytes, read_time FROM pg_stat_io WHERE context='vacuum' AND object='relation' AND backend_type='client backend'`.
4. Run, with `2> vac_ARM_REP.log`:
```
python3 tools/reproduce/measure.py --pid $PMPID -- $BIN/psql -X -h $SOCK -p 15471 -U postgres -d postgres -At -c "VACUUM (VERBOSE) t48"
```
   This gives wall, server CPU and peak RSS.
5. Afterwards, take the same snapshots again and `fincore` the main fork. Stop the server.

**Schedule:** 5 repetitions, arms in ABBA order, per table.

**Controls:**
- `t16` on both arms.
- `t48` with `-c maintenance_io_concurrency=0`. Advice is off in both arms, so they should be identical.

**Optional variants for window size:**
- `-c maintenance_io_concurrency=64` with `VACUUM (VERBOSE, BUFFER_USAGE_LIMIT '64MB')` lets the window span about 20 runs.

## what to measure
- **Latency:** the VACUUM wall time under `measure.py`, and the verbose line `elapsed:` in "system usage".
- **Server-side read time:** the verbose `I/O timings: read: X ms`, and the `pg_stat_io` read_time delta for context vacuum.
- **Server CPU and peak RSS:** from `measure.py`.
- **Decision counters:**
  - `fadvise64` call count. Run postmaster under strace as a child: `strace -f --seccomp-bpf -qq -e trace=fadvise64 -o TRACE $BIN/postgres -D DATA -p PORT -k SOCK -c ... &`. Count lines in TRACE.
  - Resident 4 kB pages of the table after the scan (`fincore`). Fix should be about 2 x scanned blocks (96,000 for `t48`). Parent should be well above that, because of kernel read-ahead overshoot into the gaps.
  - `/sys/block/sda/stat` sectors-read delta (device bytes read). Parent should be higher.

## expected effect
- **t48:** parent has about 1,000 `fadvise64` calls (one per run) and fix about 3,000. Resident pages after the scan: parent roughly 2x the fix's. VACUUM wall time on a cold rotational RAID: parent about 8-20 s, fix about 4-10 s, ratio about 1.3-2.2. CPU is similar, slightly higher on the fix because of more fadvise calls. Peak RSS is identical.
- **t16 and `maintenance_io_concurrency=0`:** ratio 1.00 within noise, and equal `fadvise64` counts. These show the harness has no arm bias.
- **t96:** ratio between `t48` and 1. Beyond the look-ahead window both arms rely on kernel read-ahead.

## cheap check (under a minute, run before the repetitions)
1. **Device emulation.**
   - Use the existing 1 GiB `$CLIFF_DATA/pgdata/decay-outruns-growth/calib.bin`. Layout: 327 runs, period 400 blocks, run 48 blocks.
   - Drop the cache, then consume each run with three sequential 128 kB `preadv` calls.
   - Parent-like: before consuming run k, `fadvise(WILLNEED)` only the first 128 kB of runs k+1 and k+2.
   - Fix-like: advise all three chunks of runs k+1 and k+2.
   - Alternate P, F, P, F, P, F, dropping the cache between each. If P/F is under 1.15, the device masks the effect, so record that and stop.
2. **Mini table.** Build N=40,000 blocks with the same layout and delete pattern, and run `VACUUM (VERBOSE)` once per arm under the strace command above.
   - Expected output: "4801 scanned (12.00% of total)", "0 dirtied", and read-timing lines.
   - Expected `fadvise64`: parent about 100, fix about 300. If both are about 100, the look-ahead window never spans a jump.

## risks
- The RAID controller cache or a fast backing device may hide the stalls (ratio around 1.1).
- The existing page cache must be genuinely empty. Check `fincore`, because 99 GB of cache is present.
- Dirty writeback from setup can disturb timings. Run `sync -f` and wait for `Dirty` in `/proc/meminfo` to fall before each repetition.
- Another user on the disk. Load average was about 5 when I looked. Use the machine lock.
- VACUUM must stay read-only. If `0 dirtied` fails, the pages are being cleaned, so redo setup. Check `pg_prepared_xacts`.
- Kernel read-ahead overshoot assumes gaps of at least 2 MB. Smaller gaps make the overshoot useful to the next run and shrink the parent's penalty.
- The distance and window assumption needs `maintenance_io_concurrency > 0` and the default ring.
- `ANALYZE` was considered and rejected: it has no controlled long runs.

---

# Item 2: postgres/waiter-count-oscillates

## fix and parent
- **Fix:** `82a4edabd272` (master), committed 2023-08-14 11:33 -0700, "hio: Take number of prior relation extensions into account".
- **Parent:** `94f9c0874216`, 2023-08-14, "pgtest: fix spacing".
- A backpatch exists, `d37ab378b6e7` (REL_16, parent `2243ef8dd6fb`). Do not use it.
- Catalog version is 202307261 on both, so one data directory serves both arms.

## the decision
At `src/backend/access/heap/hio.c@94f9c0874216`, `RelationAddBlocks`:
- 270: `extend_by_pages = num_pages`.
- 273: `waitcount = RelationExtensionLockWaiterCount(relation)`. That is `lmgr.c:466` into `lock.c:4646`, `waiters = lock->nRequested`. It counts holders as well as waiters. So one other backend inside an extension is enough for waitcount to be 1.
- 284: `extend_by_pages += extend_by_pages * waitcount`.
- 290: `Min(.., 64)`.
- 324: `ExtendBufferedRelBy`. In `bufmgr.c@94f9c0874216`, `smgrzeroextend` runs under the extension lock (908, 1877, 2057, 2067).

In `src/backend/storage/smgr/md.c:580`, an extension of more than 8 blocks uses `FileFallocate`. A smaller one uses `FileZero`, which is `pwritev` of zeros.

Why COPY flips: `copyfrom.c:65` and `copyfrom.c:71` set `MAX_BUFFERED_TUPLES` 1000 and `MAX_BUFFERED_BYTES` 65535. For a one-int column, a 1000-tuple batch needs 5 pages (`heapam.c:2062` `heap_multi_insert_pages`). With no other backend in extension the size is 5 (`pwritev`). With a holder or waiter present it is 10, 15, 20 and so on (`fallocate`). So it flips per extension.

The fix, `hio.c@82a4edabd272`:
- 302: `if (bistate) extend_by_pages = Max(extend_by_pages, bistate->already_extended_by)`.
- 430: `bistate->already_extended_by += extend_by_pages`, a cumulative total. It starts at 0 (`heapam.c:1779`).
- Per-backend sizes become roughly 5, 5, 10, 20, 40, then 64. It is monotone and always fallocate after the first two extensions. The oscillation is gone, and extension is far more aggressive even without concurrency.

## does it show in latency?
**Doubtful on this host.**

- The reported penalty is that XFS performs badly when extension alternates between `fallocate` and `pwritev`. This host has only ext4, and no xfs module and no root.
- A COPY wall-time difference can still show through the other half of the fix. Extension calls fall from about 3,500 to about 300 for a 4M-row COPY, and extending more aggressively with no concurrency was claimed as a gain.
- That would be a different mechanism from the oscillation. Report it as such, using the K=1 comparison below.
- Direct evidence of any switching penalty on ext4 comes from strace -T below.

## trigger
- A shared, committed table (not new in the transaction, so `RELATION_IS_LOCAL` is false).
- Several concurrent COPYs of narrow rows into it. Use a one-int `UNLOGGED` table so WAL is not the bottleneck and extension is a visible share.
- K at least 2. K=1 is the no-oscillation control for the filesystem effect: the parent always uses `pwritev` of 5 pages and the fix grows to `fallocate` of 64.

## workload
**Builds:** `tools/reproduce/build.sh postgres 94f9c0874216` and `... 82a4edabd272`.

**Server, same for both arms:**
- Data dir `$ROOT/pgdata/waiter-count-oscillates/data`, port 15472.
- Extra options: `-c shared_buffers=1GB -c max_connections=64 -c autovacuum=off -c track_io_timing=on -c synchronous_commit=off -c checkpoint_timeout=1h -c max_wal_size=32GB -c bgwriter_lru_maxpages=0`.
- Setup (once): `CREATE UNLOGGED TABLE c(a int);`
- Data file: 4,000,000 lines, one integer per line, e.g. `python3 -c "print('\n'.join(map(str,range(4000000))))" > rows.csv`.

**One repetition (arm, K):**
1. Restart that arm's server fresh on the same data dir.
2. Run `TRUNCATE c; CHECKPOINT;`, then `sync -f <datadir>`. Wait until Dirty+Writeback in `/proc/meminfo` is under about 200 MB.
3. Snapshot `pg_stat_io` where `backend_type='client backend' AND object='relation' AND context='bulkwrite'`: `extends`, `extend_time`.
4. Start the `Sampler` (as in `measure.py`) on the postmaster pid. Optionally start one more psql with `\watch 0.05` over `pg_stat_activity` filtered to `query LIKE 'COPY%'`, grouped by `wait_event_type, wait_event`. The signals are `Lock:extend` and `IO:DataFileExtend`.
5. Launch K `psql -X -At -h SOCK -p 15472 -U postgres -c "COPY c FROM '/abs/rows.csv'"` processes together.
6. Record each process's wall time. Compute the mean and the maximum across sessions.
7. Afterwards check `count(*) = K*4,000,000`, take the `pg_stat_io` delta, and read the Sampler's CPU and peak RSS.

**Schedule:** K in {1, 2, 4, 8, 16}, 5 repetitions each, ABBA arm order.

**Optional booster:** the same with `COPY ... (FORMAT binary)`, so parse cost shrinks and extension is a larger share.

## what to measure
- **Latency:** per-session COPY wall time (mean and max across sessions), and the verbose-free `\timing` figure.
- **Server CPU and peak RSS:** from the Sampler.
- **Extension time:** `pg_stat_io` `extend_time` and `extends` deltas. This is total ms in extension and blocks extended. Block counts should be equal between arms.
- **Decision counter:**
  - Run the postmaster under `strace -f --seccomp-bpf -qq -T -y -e trace=fallocate,pwritev -o TRACE $BIN/postgres -D DATA -p PORT -k SOCK -c ... &` for the check runs only. Do not time those runs.
  - From the per-backend sequences, count `pwritev` versus `fallocate` calls on the relation file, their sizes, and the number of switches between the two.
  - Compare the `-T` duration of calls that follow a switch with calls of the same type that follow the same type. That is a direct ext4 switching-penalty test.
- **Wait-event shares:** from the `\watch` sampler.

## expected effect
- **Decision counters:** parent shows a mix of `pwritev` (about 40 kB) and `fallocate` (80 kB to 320 kB), with hundreds to thousands of switches per backend for K at least 4. Fix shows at most 2 switches per backend, with 95% or more `fallocate` of 524,288 bytes.
- **K=1:** parent about 3,500 `pwritev` calls, fix about 300 `fallocate`.
- **Latency on ext4:** parent/fix between 1.00 and 1.15, and possibly nothing. The XFS penalty cannot appear here.
- **Mixed:** at K at least 2 the fix also enters up to 59 pages per extension into the FSM, which adds CPU. The sign at high K is unknown, so treat any K-dependent difference carefully.
- **If the switching penalty is invisible:** strace -T shows post-switch calls no slower than same-type calls, and the K=1 ratio equals the K=4-8 ratio. Then record "decision differs, latency does not on ext4".
- **CPU and peak RSS:** about equal.

## cheap check (under a minute)
- Run K=4 COPYs of 500,000 rows each into `c`, with the postmaster under the strace command above.
- Expected in the parent: both `pwritev` and `fallocate` appear on the relation fd, with multiple switches per backend.
- Expected in the fix: fallocate dominated, with sizes growing to 524,288 bytes.
- If the parent shows only `pwritev`, there is not enough extension-lock overlap. Raise K, use the binary booster, or check that rows are narrow. A one-int row gives 5 pages per batch. Wider rows give more than 8 pages and the parent would always fallocate, with no oscillation.

## risks
- No xfs available, so the reported penalty cannot be created. The best case is a small gain on ext4.
- The table must not be created or truncated in the same transaction as the COPY. Otherwise `RELATION_IS_LOCAL` is true, waitcount is 0, and `TABLE_INSERT_SKIP_FSM` is set.
- Dirty writeback from earlier work can add noise. Run `sync` first.
- The 2023 tree must build with GCC 15.3 under `build.sh`. If it does not, no build is possible for either arm.
- Strace changes timing, so use it only in separate check runs.
- Row width: one int column gives 5 pages per 1000-tuple batch. Any change that pushes the batch above 8 pages removes the oscillation.

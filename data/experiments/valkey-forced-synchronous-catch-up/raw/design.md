Both items can show in latency; I read the code and mirrored item 1's arithmetic in a Python simulation. Nothing was built or run here, so the sizes below are predictions, and the cheap checks are there to confirm them.

Ports 15400-15499 are the project's; keep the probe and driver off the server's core with `taskset`. Binaries are at `$CLIFF_DATA/build/valkey-<12sha>/src/src/valkey-server`.

# Item 1: valkey/banked-negative-overage

## fix and parent
- Fix: `0c8ad5cd3412` (author date 2024-12-11 09:47 -0800), "defrag: allow defrag to start during AOF loading (#1420)".
- Parent (first parent): `1acf7f71c032` (2024-12-11), "Fix memory leak in the new hashtable unittest (#1421)".
- The fix bundles two changes:
  - The clamp of negative overage, which is this item's decision.
  - A start of defrag from `defragWhileBlocked`, reached only while loading or running a long script.
- A workload that never blocks sees only the clamp.

## the decision
`src/defrag.c` runs defrag as a list of stages: for each db a keys stage and an expires stage, then pubsub x2, lua and module. Each call of the timer proc `activeDefragTimeProc` gets a time budget (the "duty") from `computeDefragCycleUs`, runs the current stage until that budget ends, then `computeDelayMs` picks the sleep before the next call.

- **What it measures:** after each call, `overage = end_time - intendedEndtime`, in signed microseconds. It is negative when a stage finishes early.
- **What it keeps:** `defrag.timeproc_overage_us`, a `long`. At the parent it is added to without limit, so negative values accumulate.
- **What it compares and chooses:** the next call's duty is `P*waited/(100-P) - overage`, floored at `active_defrag_cycle_us` (default 500 us). Subtracting a negative overage lengthens the duty. The delay is `total - cycle + overage*(100-P)/100`, with `total = cycle*100/P`.

Deciding lines at the parent (`1acf7f71c032`):
- `src/defrag.c:1158` `dutyCycleUs = targetCpuPercent * waitedUs / (100 - targetCpuPercent);`
- `src/defrag.c:1161` `dutyCycleUs -= defrag.timeproc_overage_us;`
- `src/defrag.c:1164-1167` the floor at `active_defrag_cycle_us`.
- `src/defrag.c:1179` `int overage = defrag.timeproc_end_time - intendedEndtime;`
- `src/defrag.c:1180` `defrag.timeproc_overage_us += overage;`
- `src/defrag.c:1192` the delay line, with the comment "overage might be negative".

At the fix (`0c8ad5cd3412`):
- `src/defrag.c:1183` `if (defrag.timeproc_overage_us < 0) defrag.timeproc_overage_us = 0;`
- `src/defrag.c:1179` `overage` becomes `long`.
- `src/defrag.c:1261` the new `defragWhileBlocked` start.

How a spike forms: each empty stage (an empty db) ends in a few microseconds but was given its whole duty, so it banks about -(duty - 5 us). The next duty is then larger by that amount. With P = 1%, the duty grows as `duty(k+1) ~ 0.99*duty(k) + 500 us`, and the bank is spent on the first stage that has real work. The most it can reach is `cycle*100/P`, which is 50 ms. The single event-loop call then runs for the whole duty and blocks every client.

## does it show in latency?
Yes. The main thread is blocked for one duty-length call, which is 13 ms with the default 16 dbs and about 35 ms with 64 dbs. The fixed arm stays near 0.5 ms. The server also records the cycle itself as the latency event `active-defrag-cycle` (`src/defrag.c:1242`).

My simulation (Python mirror of `computeDefragCycleUs` / `computeDelayMs` and the 30 empty stages) gives these duties for the first real stage:

| Setup | Parent duty | Fixed duty | Arrives (parent / fixed) |
|---|---|---|---|
| 16 dbs (30 empty stages before db15 keys) | 13.0-13.4 ms | 500 us | about 1.26 s / 1.47 s after cycle start |
| 64 dbs (126 empty stages) | about 35 ms | 500 us | about 3.5 s / 6.1 s |

The result barely changes with timer rounding (tried -900 us to +1000 us).

## trigger
- Active defrag is running at P = 1% CPU: set `active-defrag-cycle-min 1` and `active-defrag-cycle-max 1`. At higher P the maximum duty shrinks to `cycle*100/P` (about 3.7 ms at P = 25).
- Many consecutive stages finish instantly, followed by a stage with real work. So all fragmented data is in the highest-numbered db (db15), and **db0 and db1-14 are empty**.
- Do not put keys in db0. A real stage resets the bank. If data is only in db0, the bank is spent on the trailing empty stages and no spike shows.
- Fragmentation is above the thresholds. Each defrag cycle restart gives one fresh spike.

## workload
Server (`respclient.start` already adds `--port`, `--bind 127.0.0.1`, `--save ""`, `--appendonly no`):
```
taskset -c 2 valkey-server --enable-debug-command yes --loglevel verbose --logfile LOG \
  --latency-monitor-threshold 5 --activedefrag no \
  --active-defrag-cycle-min 1 --active-defrag-cycle-max 1 --active-defrag-ignore-bytes 1mb
```
- `hz` stays at the default 10 and `databases` at the default 16.
- Build both arms with `tools/reproduce/build.sh valkey 1acf7f71c032` and `... 0c8ad5cd3412`.
- Check `CONFIG SET activedefrag yes` returns OK. If it errors, the build has no jemalloc defrag.

Load, in Python with `respclient.Resp`:
```python
r = Resp(port); r.cmd("SELECT", 15)
r.cmd("DEBUG", "POPULATE", 2000000, "k", 100)        # k:0..k:1999999, 100-byte values, about 3 s
for i in range(1, 2000000, 2): UNLINK k:i            # 1000 keys per command, about 500 commands per pipeline
```
- This leaves about 1M survivors and 100% small-bin fragmentation.
- Check `INFO memory` shows `allocator_frag_ratio >= 1.4` and `allocator_frag_bytes` above 50 MB.

Measured phase, about 46 s:
```python
pr = Probe(port, 0.001, cpu=6); pr.start()   # PING every 1 ms, separate process
# wrap the whole phase in: tools/reproduce/measure.py --port P -- python3 phase.py
time.sleep(2)
for _ in range(10):
    r.cmd("CONFIG", "SET", "activedefrag", "yes"); time.sleep(4.0)   # ramp then real stage
    r.cmd("CONFIG", "SET", "activedefrag", "no");  time.sleep(0.3)   # must exceed one 50 ms timer period
s = pr.stop()
```
- Each restart begins a new defrag cycle from stage 0, so each gives one spike.
- The 4 s window covers both arms' ramp (1.5 s).
- Restarts re-scan the same first part of the keyspace, so fragmentation stays high.
- A natural single cycle gives only one spike per cycle, which is why the restarts are used.

Optional amplified variant: `--databases 64`, data in db63 (`SELECT 63`), a 10 s restart period. Expect a spike of about 35 ms against 0.5 ms.

Run the two arms alternately, 3-5 repetitions.

## what to measure
- **Probe:** `raw_max_ms`, `raw_over_10ms`, `blocked_ms`, and `cor_p999_ms`. The spikes are rare in sample count, so p99 will not move.
- **Server side, after the phase:** `LATENCY LATEST` and `LATENCY HISTORY active-defrag-cycle`, which keeps one maximum per second.
- **Decision shown:**
  - the verbose log lines "Starting active defrag, frag=..%, ..., cpu=1%", one per restart, which confirm each restart began a cycle;
  - `INFO` `active_defrag_running:1`, which confirms P = 1;
  - `active_defrag_hits` and `total_active_defrag_time`.
- **Beside it:** `measure.py` `cpu_s` and `peak_rss_mb`.

## expected effect
- Parent: about 10 spikes per run (one per restart) of about 13 ms.
  - `raw_max` about 13-14 ms, `raw_over_10ms` about 8-10, `blocked_ms` about 100-130.
  - `active-defrag-cycle` events of 12-14 ms.
- Fixed: `raw_max` about 1-2 ms, `raw_over_10ms` 0, no `active-defrag-cycle` event at threshold 5.
- The `latency-monitor-threshold` is 5 because the event timer has 1 ms resolution, so a 0.5 ms call would otherwise register as 1 ms about half the time.
- CPU and peak memory should be equal: defrag is about 1% of a core in both arms (a few tenths of a second over the window), and the data is the same.

## cheap check (under 1 minute)
After the load, set `CONFIG SET activedefrag yes`, wait 3 s, then run `LATENCY LATEST`.
- Parent: an `active-defrag-cycle` entry with max about 12-14 ms.
- Fixed: no entry.
- Both: `INFO` shows `active_defrag_running:1` and the log has "Starting active defrag ... cpu=1%". If it is not 1, the cycle-min/max pin did not take. If no "Starting" line appears, fragmentation is below the thresholds.

## risks
- No jemalloc defrag in the build, or fragmentation below the ignore-bytes threshold.
- Data not in the highest-numbered db, or any key in db0. Check that the empty dbs really are empty.
- P above 1 shrinks the spike.
- Fragmentation falling below the thresholds before the last restart. Check that the "Starting active defrag" count equals the number of restarts.
- The `no` to `yes` gap must exceed the 50 ms timer period, or the cycle is not restarted.
- Two arm differences: the fixed arm needs about 0.2 s longer to reach db15, and the fixed commit also starts defrag from `defragWhileBlocked`. Neither matters without blocking.
- Probe and server noise: pin cores.

# Item 2: valkey/forced-synchronous-catch-up

## fix and parent
Two commits match the subject, with identical file content at their parents (no diff in `hashtable.c`, `t_set.c`, `server.c`, `kvstore.c` or `debug.c`):
- Fix on `unstable`: `aefed3d363d1` (2025-08-15), parent `dcbaecddce5d`. Recommended.
- Backport on the 9.0 branch: `88e227d3d6ff` (committed 2025-09-23, author date 2025-08-15), parent `b58ac2990251`.
- Subject for both: "Don't allow resize hashtable if rehashing is ongoing (#2465)".

## the decision
`src/hashtable.c` `resize()` is reached from `hashtableExpandIfNeeded` (on insert) and from the explicit `hashtableExpand` / `hashtableTryExpand`. At the parent, if a resize is requested while the table is rehashing and not paused, `resize` runs every remaining rehash step in a loop and then starts a new resize.

Deciding lines at the parent (same line numbers at `dcbaecddce5d` and `b58ac2990251`):
- `src/hashtable.c:616` `old_exp = bucket_exp[hashtableIsRehashing(ht) ? 1 : 0]`, and "same exp, return false" just after.
- `src/hashtable.c:628` `if (hashtableIsRehashingPaused(ht)) return false;` (paused: no loop).
- `src/hashtable.c:629` the loop `while (hashtableIsRehashing(ht)) { rehashStep(ht); }`.
- `src/hashtable.c:679-680` `expand()` only refuses `if (size < hashtableSize(ht))`.
- `src/hashtable.c:1272-1277` `hashtableExpandIfNeeded`: `min_capacity = used[0] + used[1] + 1`, compared with the capacity of table 1 while rehashing.

At the fix (`aefed3d363d1`):
- `src/hashtable.c:606` `assert(!hashtableIsRehashing(ht));` in `resize`.
- The fast-forward loop is removed, and `old_exp = bucket_exp[0]` (line 620).
- `src/hashtable.c:672` `hashtableIsRehashing(ht) || size < hashtableSize(ht)` in `expand`.
- `src/hashtable.c:1264` `hashtableExpandIfNeeded` returns false if rehashing.

## does it show in latency?
Yes, narrowly: one stall of roughly 0.1-0.3 s per run, on a natural path, and only for the internal tables of big set, hash or zset values. Here is what I ruled out:

- **Main keyspace (`db->keys`):** unreachable.
  - Each new key takes two rehash steps (`lookupKeyWrite` plus `dbAdd`).
  - `serverCron` adds a 1 ms rehash budget through `kvstoreIncrementallyRehash` (`src/server.c:1301`).
  - A grown table (50% full) needs 7B more inserts to overflow, but the rehash needs only B steps.
- **Set, hash and zset internal tables:** they have no cron rehash, and `SADD` takes exactly one step per member. `setTypeAddAux` (`src/t_set.c:148`) calls `hashtableFindPositionForInsert`, whose `findBucket` steps once.
- **After a shrink:** a shrink (`hashtableShrinkIfNeeded`, below 13% fill, `MIN_FILL_PERCENT_SOFT` at `src/hashtable.c:90`) makes a new table that is about 52% full, and rehashing starts. Refilling takes about 0.84B inserts to pass 100% of the new table. That uses only about 0.84B of the B rehash steps, so about 16% of the old buckets are still unmoved when the expand check fires.
- **Growth rehash:** it cannot overflow, because 7B inserts are needed and B steps finish it first.
- **`DEBUG POPULATE`:** it reaches the branch, but its own loop dominates the command, so it is not an isolated stall. The same moves would happen in the fixed arm through the loop's steps, so it is not a clean trigger.

## trigger
- A hashtable-encoded set (non-integer string members, more than 128 entries) of 2^22 buckets that has been shrunk by `SREM` to exactly the 13% threshold, followed immediately by `SADD`s of new members.
- No command touches that set's rehash between the shrink and the refill. `DEBUG HTSTATS-KEY` and `SCARD` do not step the set's rehash.
- The resize policy must be ALLOW, so there is no child process (no BGSAVE).

Arithmetic for the primary size, B = 2^22 buckets:
- Table 0: `cap0 = 7 * 4,194,304 = 29,360,128`.
- Shrink trigger: `T = 3,816,816` entries (`T*100 <= cap0*13`, and `T+1` is not).
- Table 1 after the shrink: 2^20 buckets, so capacity 7,340,032.
- Overflow: the 3,523,217th new insert, after 3,523,216 inserts (and as many steps).
- At the overflow, 671,087 buckets remain, holding about 0.61M entries.
- The parent then moves all of them in one command, frees the old table, and starts the next resize to 2^21 buckets (14,680,064).

Other sizes:

| B | n0 members | Members to remove | Table 1 buckets | New inserts to overflow | Unmoved buckets / entries | Expected stall |
|---|---|---|---|---|---|---|
| 2^18 (cheap check) | 1,500,000 | 1,261,449 (T = 238,551) | 2^16 | 220,202 (trigger insert) | 41,942 / about 38k | 5-15 ms |
| 2^21 | 10,000,000 | 8,091,592 (T = 1,908,408) | 2^19 | 1,761,609 (trigger insert) | 335,543 / about 305k | 60-70 ms |
| 2^22 (primary) | 20,000,000 | 16,183,184 (T = 3,816,816) | 2^20 | 3,523,217 (trigger insert) | 671,087 / about 0.61M | 100-300 ms |
| 2^23 (if signal is weak) | 40,000,000 | 32,366,367 (T = 7,633,633) | 2^21 | 7,046,432 (trigger insert) | 1,342,176 / about 1.22M | 200-500 ms |

## workload
Server:
```
taskset -c 2 valkey-server --enable-debug-command yes --latency-monitor-threshold 20
```
(plus the `respclient.start` defaults: `--save ""` and `--appendonly no`, so no child process). Build both arms with `tools/reproduce/build.sh valkey dcbaecddce5d` and `... aefed3d363d1`.

Use members like `m123` and `n123`. Do not use integer-looking names, which would make an intset.

Phase A (build), unmeasured:
```
SADD S m0 ... m999 (and so on to m19,999,999)    # 1000 members per command, about 20 commands per pipeline
```
Check A: `DEBUG HTSTATS-KEY S` shows `table size: 29360128`, `number of entries: 20000000`, and no "Hash table 1".

Phase B (shrink), unmeasured:
```
SREM S m0 ... m16183183    # 16,183 commands of 1000 members, then one of 184
```
Check B: `DEBUG HTSTATS-KEY S` shows "Hash table 1 stats (rehashing target)" with "No stats available for empty hash tables" (it is empty). Table 0 still shows `table size: 29360128`, `number of entries: 3816816`.
- Remove exactly 16,183,184 members, no more and no fewer. One fewer does not shrink. More members removed would leave the rehash further along, which shrinks the effect.

Phase C (measured), about 10-20 s:
```python
pr = Probe(port, 0.001, cpu=6); pr.start()
# wrap in: tools/reproduce/measure.py --port P -- python3 phaseC.py   (VmHWM resets at its start)
lat = []
for j in range(0, 4_500_000, 100):                 # 45,000 commands, closed loop, one at a time
    t0 = perf_counter(); r.cmd("SADD", "S", *[f"n{j+i}" for i in range(100)]); lat.append(perf_counter() - t0)
s = pr.stop()
```
- 4.5M inserts is enough for both arms to run past their own second resize. The fixed arm's rehash completes at insert 4,194,304.
- Run the arms alternately, 3-5 repetitions. One stall per repetition, so there are 3-5 events per arm.
- Phase A and B each take a minute or so in Python.

## what to measure
- **Client:** the maximum and the top 3 per-command latencies of the `SADD` stream. The stall should land at about command 35,233.
- **Probe:** `raw_max_ms`, `blocked_ms`, `raw_over_100ms`.
- **Server:** `LATENCY LATEST`, event `fast-command` (SADD is flagged FAST).
- **Decision:** `DEBUG HTSTATS-KEY S` after phase C.
  - Parent: table 0 is the shrunk table (about 7.3M entries) and table 1 is `14680064` (the new rehash target).
  - Fixed: the old table is gone or still shrinking, and no second table has been started yet at the point of overflow.
- **Beside it:** `cpu_s` and `peak_rss_mb` from `measure.py` for phase C.

## expected effect
- Parent: one stall of about 100-300 ms.
  - The remaining 0.61M entries are rehashed at roughly 0.15-0.3 us each (hashing and cache misses).
  - It also frees the 256 MB old table and callocs the next 128 MB table.
- Fixed: the insert goes past 100% fill of the shrunk table while rehashing continues. There is no sync catch-up. A smaller event (the 128 MB calloc and 256 MB free) may still show at the end of the rehash, likely under 10-40 ms. That is the comparison floor.
- CPU: about the same within 5-10% (the parent starts the growth rehash about 0.67M inserts earlier, so it does a little more work inside the window).
- Peak RSS: about the same in phase C. Parent frees the old table before allocating, while fixed holds both for a while, so fixed may be slightly higher.

## cheap check (under 1 minute)
Use the 2^18 size, which takes only a few seconds.
- Build 1,500,000 members, `SREM` exactly 1,261,449 members, then `SADD` 230,000 new ones (single-member `SADD`s in pipelines of 100, timing each pipeline).
- `DEBUG HTSTATS-KEY S` after:
  - Parent: table 0 `table size: 458752` and table 1 `table size: 917504`. One pipeline at about insert 220,202 shows 5-15 ms.
  - Fixed: table 0 `table size: 1835008` and table 1 `table size: 458752` (still rehashing). No pipeline over about 2 ms.
- If the parent shows the sizes but not the stall, the stall is below the noise at this size; go to 2^22.

## risks
- Any other command that touches the set's rehash between phases B and C advances the rehash and shrinks the effect. Keep that set untouched.
- A BGSAVE or other child switches the policy to AVOID or FORBID. Check that no child exists.
- A shrink that fires at a different count (the exact removal count above matters) leaves different headroom.
- The second-resize floor in the fixed arm depends on how jemalloc recycles large extents.
- Phases A and B are slow in Python at the 2^22 size.
- The effect is a single event per run, so use enough repetitions.
- Memory per run is about 1 GB for the 20M-member set (about 2 GB at 2^23).
- This is natural only for big set, hash or zset internals; the main keyspace never reaches it.
- Possible further check: if you want proof that the loop never runs for the main keyspace, a probe patch printing a line inside the `while` at `src/hashtable.c:629` (passed as the PATCH argument to `build.sh`) would show it, but that is not a latency reproduction.

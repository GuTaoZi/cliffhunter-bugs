I read the code and wrote both designs from it. I did not build or run anything, so every number below is an estimate from the code. Neither tree is built yet (no redis-02a87885e64c or redis-dcd0b3d02013 in the build dir). Both fixes are adjacent to their parents and touch only the file named, so nothing else differs between arms.

All paths below are in `$CLIFF_DATA/src/redis`. Build binaries come from `build.sh redis <sha>` (MALLOC=jemalloc, so defrag is available) at `$OUT/src/src/redis-server`, with `OUT=$CLIFF_DATA/build/redis-<12char>`.

# Item 1: redis/empty-sample-means-repeat

**fix and parent**
- Fix: `f20774eced7e`, 2024-02-05, "Fix active expire timeout when db done the scanning (#13030)". It changes only `src/expire.c` and one test line.
- Parent: `02a87885e64c`, 2024-02-04.

**the decision**
- Active expire samples ~20 keys per loop from the expires dict and repeats the loop while the sample looks stale.
- At the parent, `src/expire.c:296-299` calls `dbScan` and breaks if `db->expires_cursor == 0`.
- `src/expire.c:308` then sets `repeat = data.sampled == 0 || expired*100/sampled > acceptable_stale`, so zero samples means repeat.
- The loop ends at `:354` (`while (repeat)`). The time limit is checked only every 16 iterations (`:342`), and `:346` increments `stat_expired_time_cap_reached_count`.
- `isExpiryDictValidForSamplingCb` (`:146-157`) returns C_ERR when `buckets > 4 && dictSize*100/dictBuckets < 1`. `dictBuckets` is size0+size1 (`dict.h:156-157`), so a rehashing dict counts both tables.
- In `src/db.c:1527` the dict is flagged invalid. With no other slot (`:1534-1541`, `dbGetNextNonEmptySlot` returns -1 in standalone mode), `dbScan` returns 0 with nothing sampled.
- So `sampled==0` and `cursor==0` on every iteration, and the loop spins until `timelimit` expires.
- The slow cycle (`server.c:1165` via `databasesCron`, `expire.c:218`) has `timelimit = 25*1e6/hz/100 = 25 ms` at hz 10.
- Once a cycle hits the cap, `timelimit_exit` stays 1, so the fast cycle in `beforeSleep` (`server.c:1776`, `expire.c:194-198`) also runs. It burns about 1 ms, at most once per 2 ms.
- Fix (`expire.c@f20774eced7e`): `:248` adds `int db_done = 0`, `:298-299` sets `db_done = 1` when the cursor is 0, and `:313` becomes `repeat = db_done ? 0 : (...)`. The cycle then exits at once.

**does it show in latency?** Yes. The main thread spins 25 ms of every 100 ms in the slow cycle, plus about 1 ms of every 2-3 ms in fast cycles whenever requests arrive. A PING that arrives during a burn waits for it, and fast cycles run before the reply is flushed.

**trigger**
- A fork child is alive, so dict resize policy is AVOID (`server.c:751-753`) and `databasesCron` does not call `tryResizeHashTables` or `incrementallyRehash` (`server.c:1177`).
- The expires dict was large and then mass-deleted.
- Shrink starts at ≤1/32 fill (`dict.c:1524-1527`), but rehash advances only about one bucket per touch of that dict (`dict.c:387-395`, `_dictRehashStep`).
- With the rehash stuck, size0 stays big and elements/(size0+size1) falls below 1%. The dict is then "invalid" for sampling, permanently while the child lives.
- With N=300,000 TTL keys: size0 = 524288, and shrink starts at used ≤ 16384 with size1 = 16384.
- Deleting down to R=300 keys leaves 300·100/540672 = 0, which is below 1. The rehash cannot finish, because the sequential pointer reaches only about 28% of the buckets.
- The remaining keys can carry any TTL (3600 s is fine). The bug needs only a non-empty expires dict in this state.

**workload**
1. Pin the server to a core and the probe to another (`os.sched_setaffinity(p.pid, {2})`, `Probe(cpu=3)`). Start with `respclient.start()`, which already adds `--save "" --appendonly no`. Extra args:
   `--dir $SCR --hz 10 --dynamic-hz no --enable-debug-command yes --rdb-key-save-delay 10000000 --latency-monitor-threshold 5`
2. Load with `Resp.send` in batches of 20,000: `["SET", f"k{i}", "v", "EX", 3600]` for i in 0..299999. Then `INFO keyspace` should show `db0:keys=300000,expires=300000`.
3. Poll `DEBUG HTSTATS 0` every 0.2 s (up to 30 s) until neither `[Dictionary HT]` nor `[Expires HT]` contains "rehashing target". Expires table size should be 524288. Then sleep 1 s.
4. `BGSAVE`. Poll `INFO persistence` until `rdb_bgsave_in_progress:1`. The huge per-key delay keeps the child alive for the whole run.
5. Delete `["DEL", f"k{i}"]` for i in 300..299999, in batches of 20,000. Then sleep 3 s so the fork and copy-on-write noise settles.
6. Run the cheap check below.
7. Run `measure.py --port P -- python3 window.py`. `window.py` does this:
   - `reset_hwm`.
   - Read `INFO stats` and `thread_cpu_s(pid)`.
   - Run `Probe(P, 0.001, cpu=3)` for 30 s.
   - Read `INFO stats` and `thread_cpu_s` again, and print `pingprobe.summary(rows)` without the rows, plus the deltas.
8. Stop with `SHUTDOWN NOSAVE`, which kills the RDB child. Then confirm `pgrep -f redis-rdb-bgsave` finds nothing.
9. Run 4 repetitions per arm, alternating P F P F P F P F, restarting the server each time (about 75 s per run).

**what to measure**
- Latency: the PING probe's corrected p50/p99/p999, raw max, `raw_over_10ms` and `blocked_ms` over the 30 s window.
- Server-side counters (deltas over the window):
  - `INFO stats`: `expired_time_cap_reached_count` (the decision counter, `expire.c:346`) and `expire_cycle_cpu_milliseconds`.
  - `LATENCY LATEST` / `LATENCY HISTORY expire-cycle` (events of about 25 ms).
- CPU: main-thread CPU from `thread_cpu_s`, and the `measure.py` tree CPU.
- Memory: peak RSS from `measure.py`.

**expected effect**
- Parent:
  - `expired_time_cap_reached_count` rises about 10/s from slow cycles plus a few hundred/s from fast cycles under the 1 kHz probe, so roughly 10-15K per 30 s.
  - `expire_cycle_cpu_milliseconds` rises about 600-750 ms per second.
  - Main-thread CPU is about 60-80% of a core.
  - Raw p50 is somewhere between 0.1 and 1.1 ms, since fast-cycle burns hit about every second PING.
  - Raw max is about 26 ms, with roughly 150-180 raw samples over 10 ms in 30 s.
  - Corrected p99 is about 20-26 ms.
- Fix:
  - The cap-reached count does not move.
  - Expire-cycle CPU is about 0.
  - Main-thread CPU is 3-6%, just PING handling.
  - Raw p50 is about 0.05-0.1 ms, corrected p99 under 0.5 ms, and `raw_over_10ms` is 0.
- Peak RSS should be equal on both arms (the child's VmHWM is included in the tree).

**cheap check** (under 1 minute)
- Run steps 1-5, then check the following. A shortcut is N=200,000 and R=200.
  - `INFO persistence` shows `rdb_bgsave_in_progress:1`.
  - In `DEBUG HTSTATS 0`, `[Expires HT]` shows "number of elements: 300", "table size: 524288", plus a second table "(rehashing target)" with size 16384.
  - The delta of `expired_time_cap_reached_count` over 3 s is ≥25 on the parent and 0 on the fix. `expire_cycle_cpu_milliseconds` moves by ≥500 ms on the parent and about 0 on the fix.
  - `LATENCY LATEST` lists `expire-cycle` at about 25 ms on the parent only.
- Optional negative control: skip `BGSAVE`. Cron then shrinks and rehashes the dict, and both arms stay flat. This shows the child is the cause.

**risks**
- If the dict is not stuck (the "rehashing target" table is missing), check that `BGSAVE` came before the deletes, that the child is still alive, and that R is below about 5,000.
- If the child dies, the dict becomes valid again within about 100 ms and the effect disappears. Re-check `rdb_bgsave_in_progress` at the end of each run.
- GET or SET on TTL keys during measurement would advance the rehash, so use PING only.
- `hz` must stay 10 (`--dynamic-hz no`). At hz 100 the slow-cycle stall shrinks to 2.5 ms.
- The expected rates assume the 1 kHz probe. An idle server has far fewer fast cycles.
- The fork itself causes a one-off latency blip, so keep it out of the window.

# Item 2: redis/no-yield-feedback

**fix and parent**
- Fix: `f86575f210a9`, 2025-01-24, "Gradually reduce defrag CPU usage when defragmentation is ineffective (#13752)". It changes `src/defrag.c` and adds a moduleapi test.
- Parent: `dcd0b3d02013`, 2025-01-23.

**the decision**
- At the parent, `computeDefragCycles()` (`src/defrag.c:1027-1058`) sets `cpu_pct = INTERPOLATE(frag_pct, lower, upper, cycle_min, cycle_max)` and clamps it (`:1038-1046`).
- It stores the result in `server.active_defrag_running` (`:1053`), and `frag_pct` comes from `getAllocatorFragmentation` (`:852`).
- `activeDefragCycle` (`:1064`) gives itself `timelimit = 1e6*running/hz/100` per serverCron tick (`:1122`), so at hz 10 and 50% that is 50 ms of main-thread time per 100 ms.
- At the end of a scan pass (`:1160`) it resets `running = 0` and calls `computeDefragCycles()` again (`:1164`). Nothing looks at hits or at whether fragmentation fell, so effort is a pure function of the current fragmentation.
- Memory the keyspace scan cannot move stays fragmented forever, so the effort never drops. Module values without a defrag callback are the example (`module.c:13880-13894`, `:13892` returns early).
- Fix (`defrag.c@f86575f210a9`):
  - `:1075` adds `static float decay_rate = 1.0f`.
  - `:1044` adds `cpu_pct *= decay_rate`, applied before the LIMIT clamp.
  - `:1166-1181` computes `last_hits`, `last_misses` and `last_frag_pct_change` at pass end.
  - If `|change| > 2`, or fragmentation rose slightly while hits ≥1% of tries (`:1175-1176`), it sets `decay_rate = 1`. Otherwise it does `decay_rate *= 0.9` (`:1180`).
  - `:1185` passes `decay_rate` to `computeDefragCycles`.
  - Effort therefore decays by about 10% per completed pass, down to `active-defrag-cycle-min`.

**does it show in latency?** Yes, with conditions. Defrag runs inline in serverCron on the main thread. A tick whose scan does not finish stalls PINGs for the whole time limit. The stall is capped by `cycle-max` × tick, so the design must make the budget binding:
- Use `databases 1`. With the default 16 DBs, each tick advances one DB and a pass takes at least 16 ticks, so the burn is small and decay takes minutes.
- Keep a scan pass longer than the budget.
- Keep hz 10, so the stall is `E` ms per 100 ms.

**trigger**
- A module datatype without a defrag callback, using the `datatype` test module from `tests/modules/datatype.c`.
- Every other key deleted, so the 448-byte-class slabs are half empty and the surviving values cannot be moved. This is the shape of the project's own test.
- Fragmentation stays at 40% or more forever, with no hits.

**workload**
1. Build the module for each arm from its own tree: `tools/reproduce/inenv.sh "gcc gnumake" "make -C $OUT/src/tests/modules datatype.so"`. The host page size is 4096 and the cpu count is 48, so the jemalloc page check in the test is satisfied.
2. Start (pin the server to a core):
   `respclient.start(bin, P, ["--dir",$SCR,"--hz","10","--dynamic-hz","no","--databases","1","--loadmodule",$OUT/src/tests/modules/datatype.so,"--loglevel","verbose","--logfile",$SCR/redis.log,"--latency-monitor-threshold","5","--active-defrag-ignore-bytes","100kb"])`
   Leave `activedefrag no`.
3. Load 200,000 keys, batches of 10,000: `["DATATYPE.SET", f"k{i}", 1, "x"*400]`. Then delete `["DEL", f"k{i}"]` for all even i (100,000 live keys remain). Sleep 1 s.
4. Read `INFO memory`. `allocator_frag_ratio` should be ≥1.35 and `allocator_frag_bytes` ≥10 MB. Compute `F = (allocator_frag_ratio - 1) * 100`.
5. Set the thresholds so the unclamped interpolation sits at about the cap and decay bites at once. Run CONFIG SET with:
   - `active-defrag-threshold-lower 1`
   - `active-defrag-threshold-upper floor(0.9*F)` (at least 2)
   - `active-defrag-cycle-min 1`
   - `active-defrag-cycle-max 50`

   Without this step, INTERPOLATE can be several times the cap (for example 600 against a cap of 50). Decay then needs about 24 passes before any visible drop.
6. Run `measure.py --port P -- python3 win.py` with these steps:
   - Do `reset_hwm`.
   - Start `Probe(P, 0.001, cpu=3)`.
   - Run `CONFIG SET activedefrag yes` and note t0.
   - Once a second, record `INFO` fields (listed under "what to measure") and `thread_cpu_s(pid)`.
   - Run 80 s, then stop.
   - Slice `rows` by time into [0,10) (control, both arms should match), [10,40) and [45,75) (steady state), and run `pingprobe.summary` on each slice.
7. Run 4 repetitions per arm, alternating, with a fresh server each time (about 2 min per run).

**what to measure**
- Latency: PING corrected p50/p95/p99, raw max and `raw_over_10ms` per window.
- The decision field: `INFO memory active_defrag_running`, which is the effort percentage, once a second.
- Pass log lines (verbose):
  - "Starting active defrag, frag=..%, frag_bytes=..., cpu=E%".
  - "Active defrag done in D ms, reallocated=...". D is wall time per pass.
- `INFO stats`: `active_defrag_hits`, `active_defrag_misses`, `total_active_defrag_time`.
- `LATENCY HISTORY active-defrag-cycle`.
- Main-thread CPU per window and peak RSS.

**expected effect**
- Parent: `active_defrag_running` stays at about 44-50, with a log line "cpu=~50%" every pass.
  - The main thread stalls about 50 ms per 100 ms tick.
  - Steady-state corrected p99 is about 45-50 ms and corrected p90 about 40 ms.
  - Raw `raw_over_10ms` is about 8 per second. Main-thread CPU is about 40-50% of a core.
- Fix: the first pass moves the defraggable small bins and changes fragmentation by more than 2, so decay stays at 1.
  - From pass 2, hits are about 0 and `decay_rate` falls 0.9 per pass.
  - With a pass work of about 100 ms (W, the CPU time one full scan needs), effort is about 4% by t=20 s and about 3% by t=30 s.
  - In [45,75): stall 1-4 ms, corrected p99 about 1-4 ms, CPU 1-5%.
  - If W is about 300 ms, effort is about 6% at t=40 s and 4% at t=60 s.
- The first 10 s should look the same on both arms; that is the internal control.
- Peak RSS should be equal.

**cheap check** (under 1 minute)
- Run steps 2-5 with the shortcut of 20,000 live keys. Enable defrag, wait 10-15 s, and check:
  - The verbose log shows "Starting active defrag ... cpu=..%" and "Active defrag done in D ms".
  - On the parent, `cpu=` repeats the same value. On the fix it steps down pass by pass (about 50, 45, 40, 36, ...).
  - `active_defrag_hits` is flat after the first pass while `active_defrag_misses` keeps growing.
  - `allocator_frag_ratio` stays above 1.3.
- Size N from D at E=50 (D ≈ 100 ms × the number of ticks per pass). Aim for D of 150-400 ms. If D is 100 ms or less (a one-tick pass), double the live keys. If D is over 500 ms, halve them.

**risks**
- `databases 1`: with the default 16 DBs a pass lasts at least 16 ticks (1.6 s at hz 10), so decay is far too slow to see.
- The decay is applied before the LIMIT clamp, so the threshold step above matters.
- If a pass finishes inside one tick, the tick ends early and the burn is the scan time W rather than the cap. The parent's effect is then smaller but still clear.
- Any key writes or deletes during the window change fragmentation by more than 2 and reset `decay_rate` to 1. Use only PING traffic and `INFO`.
- Defrag is skipped while a fork child exists (`defrag.c:1101`), so do not run BGSAVE or AOF rewrite.
- The stall is bounded by `cycle-max`. At the default 25 and hz 10 it is only 25 ms, so use 50 for a larger signal.
- The decayed arm still runs defrag at the `cycle-min` floor, so a small residual stall remains on the fix.
- The module build must come from each arm's own `redismodule.h`. The fix does not touch the module API, so the two `.so` files are equivalent.

NOTE: my first Bash call wrote /tmp/defrag_p1.c (a `git show` redirect, my mistake). I did not delete it because deleting is also off-limits for me, so please remove it. Nothing else was touched. I could not run anything, so every effect size below is derived from code reading and from numbers in the fix commits, not measured.

## Shared setup (all three items)
- **Arms:** use the unstable pairs. Build each with `tools/reproduce/build.sh valkey <sha>`. The binary is `$CLIFF_DATA/build/valkey-<sha12>/src/src/valkey-server`.
- **Ports and pinning:** use 15440-15449. Pin the server and the probe to two different physical cores (check `lscpu -e`; this host is an Xeon 6521P with 2 threads per core, 144 MB L3, tsc clocksource, 4 KB pages, 125 GB RAM). `respclient.start()` does not pin, so call `os.sched_setaffinity(p.pid, {core})` afterwards.
- **Probe:** `pingprobe.Probe(port, interval, cpu)`. Filter `rows` by unix time to the window you care about, then call `pingprobe.summary(rows)`.
- **CPU and RSS:** use `measure.Sampler` over the same window, as `bugs/systems/valkey/blind-to-target-overload/repro/run.py` does.
- **Latency events:** in this tree `latencyAddSampleIfNeeded` takes microseconds. `latency-monitor-threshold N` records events of at least N ms, with microsecond precision, and LATENCY HISTORY holds one per-second max stored as truncated ms. Set `latency-monitor-threshold 1`.
- **Defrag preconditions:** the jemalloc build is vendored, so `CONFIG SET activedefrag yes` works. Pass `--save ""` and `--appendonly no`, because defrag pauses while a child process exists. Pass `--enable-debug-command yes` for DEBUG OBJECT and MALLCTL checks.

---

## 1. valkey/coarse-time-check

**fix and parent**
- **Fix:** d6e011f955b1 (2025-08-29, unstable), "Reduce active defrag test latency by lowering hit threshold (#2553)".
- **Parent (buggy arm):** 6774d173c4a3 (2025-08-29).
- **9.0 backport:** d7fb766653d3, parent 9b14394b35e8. It is the same change; use it only as a cross-check.
- The parent already contains the scanLaterList fix (item 3), so scanLaterList checks the clock per node in both arms here.

**the decision**
- Defrag runs in time slices. `activeDefragTimeProc` sets `endtime = starttime + dutyCycleUs` (defrag.c:1165; `active-defrag-cycle-us` defaults to 500).
- The stage helper decides when to read the clock.
  - Parent, `defrag.c:885,898@6774d173c4a3`: `unsigned long long prev_defragged = ...hits;` then `if (++iterations > 16 || server.stat_active_defrag_hits - prev_defragged > 512 || server.stat_active_defrag_scanned - prev_scanned > 64) { if (getMonotonicUs() >= endtime) break; ... prev_defragged = hits; ... }`.
  - The same condition is in `defragLaterStep` at :825 and :850.
  - One loop pass is one `kvstoreHashtableScanDefrag` step, about 3-6 keys. `scanned` rises by 1 per key.
  - So the clock is read only after more than 512 moved allocations, more than 64 keys, or 17 steps.
- Fix, `defrag.c:885,898@d6e011f955b1`: `long long prev_defragged` and the condition `server.stat_active_defrag_hits > prev_defragged`. The clock is now read after any step that moved something.
- The extra overshoot is therefore bounded by min(512 moves, 64 keys, 17 steps) of work.

**does it show in latency?** Yes, but small; borderline at default sizes.
- The bound is about 512 moves, which is 0.2-1.2 ms on a 0.5 ms slice. That is only clearly above noise if each move is expensive.
- The project's own CI evidence (the big-list test showing 12-25 ms active-defrag-cycle events at the parent) is not explained by this bound. Treat it as CI noise on top of the real effect.
- Moves of 10 KB blocks maximise the effect.

**trigger**
- Active defrag running, with many small keys that are defragged inline (up to 1000 fields).
- Each key moves at least one allocation, and each move is costly. Use 6 members of 10 KB per key, so jemalloc bin 10240 has 2 regions per slab.
- Fragmentation: interleave the allocations of different keys and delete every other key. That leaves one live region in each slab.
- If hits are 0, both arms read the clock by the iteration and scanned rules, and nothing differs.

**workload**
1. Start the server with `--latency-monitor-threshold 1 --lazyfree-lazy-user-del no`.
2. Run `CONFIG SET`: `active-defrag-threshold-lower 5`, `active-defrag-ignore-bytes 1mb`, `active-defrag-cycle-min 40`, `active-defrag-cycle-max 40`. Leave `active-defrag-cycle-us` at 500 (condition A). Condition B is 100, optional.
3. Populate. NK=100,000 keys `s:%06d`. Do it round-robin: for r in 0..5, for each key k, send `SADD s:k member`.
   - The member is exactly 10,000 bytes: `f"{k:06d}:{r}:"` padded with `x`.
   - Pipeline 200 commands per send. This is about 6.1 GB.
   - Sets with members over 64 B use the hashtable encoding.
4. Fragment: pipeline `DEL s:k` for odd k (50,000 DELs). Wait until `lazyfree_pending_objects` is 0 and sleep 2 s.
   - Check `allocator_frag_ratio` is at least 1.3 (expect about 1.8) and `allocator_frag_bytes` is above 1 GB.
5. Run an idle baseline probe for 5 s with defrag off: `Probe(port, interval=0.0005, cpu=PC)`.
6. Reset counters with `CONFIG RESETSTAT` and `LATENCY RESET`. Start the probe and the Sampler. Run `CONFIG SET activedefrag yes`.
7. Poll INFO every 50 ms until `active_defrag_running` is 0 on 3 consecutive polls (cap 120 s). Stop the probe.
8. Record:
   - INFO stats `active_defrag_hits`, `active_defrag_misses`, `active_defrag_key_hits`, `active_defrag_key_misses`, `total_active_defrag_time`.
   - `allocator_frag_ratio` after.
   - `LATENCY HISTORY active-defrag-cycle`.
   - The probe summary for the window, plus CPU and peak RSS from the Sampler.
9. Kill the server. Alternate the arms, 5 repetitions each.

**what to measure**
- PING raw and corrected p50, p99, p99.9, max, `raw_over_10ms` and `blocked_ms` inside the defrag window.
- The number of seconds in LATENCY HISTORY with a sample of 1 ms or more, and the maximum value. This is the cleanest server-side metric.
- Decision evidence, from INFO: hits per scanned key `H = hits/(key_hits+key_misses)`.
- Optional probe patch, identical on both arms (apply via the build.sh PATCH argument):
  - In `activeDefragTimeProc`, after `latencyEndMonitor(latency)` (defrag.c:1190), add a log2-bucket histogram of `getMonotonicUs() - endtime`.
  - Count loop passes and clock reads in `defragStageKvstoreHelper`.
  - Print both with `serverLog(LL_WARNING, ...)` in `endDefragCycle`.
  - Expected passes per clock read: about 13-17 at the parent, about 1.0-1.2 at the fix.

**expected effect**
- Total defrag CPU and peak RSS are the same on both arms.
- Parent slice overshoot is about 0-0.7 ms (mean about 0.3 ms) versus 0.03-0.06 ms at the fix.
- PING raw p99 is roughly 1.1-1.5 ms at the parent versus about 0.6 ms at the fix.
- At the parent, slices of 1 ms or more occur in most seconds. At the fix they are rare.
- Uncertainty: the cost per 10 KB move is between 1 and 3 µs. If the effect is below noise, record "decision differs, latency does not".

**cheap check (about 40 s)**
- Run at 10% scale: 10,000 keys, 600 MB.
- Confirm `CONFIG SET activedefrag yes` returns OK.
- Confirm `active_defrag_hits` is at least 20,000 within 15 s.
- Confirm `H` is between 3 and 40 and `allocator_frag_ratio` falls below 1.15.
- On the parent, LATENCY HISTORY should show at least one sample of 1 ms or more.

**risks**
- Cost per move is lower than assumed, so the effect falls below noise.
- Jemalloc's per-bin decision data refreshes only on cron, so only about 50% of survivors move.
- Defrag stops when fragmentation drops below the lower threshold, so the window is about 1-3 s.
- Probe and server on hyperthread siblings add jitter.
- Zset-style data of 8 members per key, 100 B each, would be a cheaper but weaker variant; I estimate it at only about 0.1-0.3 ms.

---

## 2. valkey/coarse-time-check-2

**fix and parent**
- **Fix:** 3213f48fd694 (2025-09-10, unstable), "Increase frequency of time check during fields active expiration (#2595)".
- **Parent:** cef8822f60b6 (2025-09-09).
- **9.0 backport:** 9709974efa30, parent b0b4fad130dc.
- The change only touches `src/expire.c`.

**the decision** (`activeExpireCycleJob`)
- Parent, `expire.c@cef8822f60b6`:
  - `:392-398`: `if ((iteration & 0xf) == 0) { /* check time limit every 16 iterations. */ if (elapsedUs(start) > (uint64_t)timelimit_us) { state->timelimit_exit = 1; ...break; } }`
  - `:264`: `data.max_entries = keys_per_loop * 4` (80 fields per key at effort 1).
  - `:314`: `if (num > keys_per_loop) num = keys_per_loop` (20 keys per pass).
  - `:474-475`: slow limit is `25% * 1e6 / hz / 100`, which is 25 ms at hz 10.
  - `:459,465`: the fast limit is 1000 µs, and the fast cycle may not start again within 2 ms of the last start.
  - `:227`: the fast cycle only runs when the previous run ended on the time limit.
  - `server.c:1846`: the fast cycle is called from beforeSleep, so it runs on every event-loop pass.
- Fix, `expire.c@3213f48fd694`:
  - `:221` adds `int time_check_mask;`.
  - `:279` sets `0xf` for KEYS.
  - `:288` sets `0x0` for FIELDS.
  - `:400-407`: `if ((iteration & time_check_mask) == 0) { if (elapsedUs(start) > timelimit_us) ...`.
  - FIELDS therefore checks the clock on every pass.
- One FIELDS pass can expire up to 20 keys x 80 fields = 1600 fields. The parent checks the clock only every 16 passes, which is up to 25,600 fields.
- The PR's own numbers imply about 0.23 µs per field. That makes one pass about 0.37 ms and 16 passes about 5.9 ms.

**does it show in latency?** Yes, strongly.
- The expiry runs on the main thread, so PINGs wait for it.
- Parent estimate: the fast cycle takes about 5.9 ms where 1 ms was intended. The slow cycle takes about 29.5 ms where 25 ms was intended.
- Fix estimate: about 1.1 ms for the fast cycle and about 25.3 ms for the slow cycle.
- The PR reports 32.7% versus 20.8% average CPU when expiring 10M fields from 10K hashes. It reports no difference for a single hash.

**trigger**
- Many hashes (about 10,000) with about 1000 fields each, all fields expiring at the same instant.
- A single hash gets one key per pass, so 16 passes are only about 0.3 ms. That makes it the negative control.
- Defaults: hz 10, `active-expire-effort 1`, no replica, no AOF.

**workload**
1. Start with `--save "" --appendonly no --latency-monitor-threshold 2`. Defaults for hz and effort.
2. Compute `T = now_ms + 90000`.
3. Load H=10,000 hashes `h:%05d`. Each gets `HSETEX h:i PXAT T FIELDS 1000 f0000 <32-byte value> ... f0999 <value>`. Pipeline 50 commands per send.
   - Abort the run if loading is not finished by T-10 s.
   - Check `expired_fields` is 0 before T.
   - Memory is about 1-1.5 GB.
4. Start the Sampler and `Probe(port, interval=0.001, cpu=PC)` at T-5 s. A second pass with interval 0.01 shows less self-induced fast-cycle load.
5. Poll INFO and DBSIZE every 50 ms. Draining is done when DBSIZE is 0 (cap 60 s). Stop the probe and Sampler.
6. Record `expired_fields`, `expired_time_cap_reached_count` and `expire_cycle_cpu_milliseconds` deltas, plus `LATENCY HISTORY expire-cycle`. In this tree the event is in µs and the threshold is in ms.
7. Alternate arms, 5 repetitions each.
8. Control: one hash with 5M fields (5000 HSETEX of 1000 fields), 1 repetition per arm. Expect no difference.
9. Optional amplifier: `active-expire-effort 10`. That gives 65 keys x 260 fields per pass and 16 passes of about 60 ms at the parent.

**what to measure**
- PING raw p50, p90, p99, max and `blocked_ms` over [T, drain end], against the pre-T baseline in the same run.
- Corrected p99.
- Max per second of `expire-cycle` in LATENCY HISTORY.
- `expired_time_cap_reached_count`.
- Drain wall time, server CPU and peak RSS.
- Separately, with no probe: average CPU% while draining. Expect about 33% versus about 21%. Record it as a CPU result, not a latency one.

**expected effect**
- With the probe at 1 kHz, every PING triggers a fast cycle.
  - Parent: raw p50 about 4-6 ms, `expire-cycle` max about 29-30 ms, and a shorter drain.
  - Fix: raw p50 at most about 0.5 ms, `expire-cycle` max about 25-26 ms.
- Effect scales with per-field cost. Anything above about 0.06 µs per field is visible.

**cheap check (about 25 s)**
- Load 2,000 hashes x 1000 fields with `T = now + 8 s`.
- Confirm `expired_fields` reaches 2,000,000.
- Confirm `expired_time_cap_reached_count` is at least 2.
- Compute per-field cost = Δ`expire_cycle_cpu_milliseconds` x 1000 / 2,000,000 µs. It should be between 0.1 and 2 µs.
- Confirm LATENCY HISTORY `expire-cycle` shows at least 25 ms on both arms, and about 3 ms or more higher on the parent.

**risks**
- Per-field cost differs from 0.23 µs.
- Load not finished before T.
- Dynamic hz changes the slow limit.
- The probe itself triggers the fast cycles; that is the design, but note it.
- Near the end of the drain, the table is sparse and `expireShouldSkipTableForSamplingCb` skips scanning, so the drain tails off.

---

## 3. valkey/sparse-deadline-checks

**fix and parent**
- **Fix:** 84fd62641900 (2025-08-20, unstable), "Refactor scanLaterList to fix latency issue (#2514)".
- **Parent:** c6c91d152fb7 (2025-08-20).
- **9.0 backport:** 4b5e09adddfb, parent 1dfb52e21a5d.
- The change is in `defrag.c` only, plus a test latency of 5.

**the decision** (`scanLaterList`, for lists with more than 1000 quicklist nodes)
- Parent, `defrag.c@c6c91d152fb7`:
  - `:401`: `if (++iterations > 128 && !bookmark_failed) {`
  - `:402`: `if (getMonotonicUs() > endtime) {`
  - `:403-404`: `if (!quicklistBookmarkCreate(&ql, "_AD", node)) { bookmark_failed = 1; }`
  - `:416`: `return bookmark_failed ? 1 : 0;`
  - The clock is read only after 129 nodes. Each call to the function processes at least 129 nodes even if the deadline has already passed.
- Fix, `defrag.c:400@84fd62641900`: `if (getMonotonicUs() > endtime) {` after every node, with the bookmark created at timeout.
- The "or never" path is unreachable in practice. `quicklistBookmarkCreate` fails only at 15 bookmarks (`quicklist.c:1624@c6c91d152fb7`), and defrag makes one.

**does it show in latency?** Doubtful (small).
- Parent extra work is at most 129 nodes per slice. At about 1.5 µs per node that is about 0.2 ms, or about 0.4 ms with cold 14 KB nodes.
- That is the same order as the 0.5 ms slice and as scheduler noise.
- It is clearer only with big nodes and a small slice budget (`active-defrag-cycle-us` 100).
- The big-list test's ms spikes are not explained by this bound.

**trigger**
- A list with more than 1000 nodes, with large moved nodes, fragmented so that most nodes move.
- Use `list-max-listpack-size -3` (16 KB limit) and 3 elements of 4500 B per node. That gives a 13.5 KB listpack in bin 14336, 2 regions per slab.
- Interleave the lists in allocation order and delete half of them.
- Only about half the survivors move, because pairs merge.
- The default `-2` (8 KB) is useless here: bin 8192 has 1 region per slab and is never defragged.

**workload**
1. Start with `--list-max-listpack-size -3 --lazyfree-lazy-user-del no --enable-debug-command yes --latency-monitor-threshold 1`.
2. Run `CONFIG SET`: `active-defrag-threshold-lower 5`, `active-defrag-ignore-bytes 1mb`, `active-defrag-cycle-min 40`, `active-defrag-cycle-max 40`.
   - Condition A: `active-defrag-cycle-us` at the default 500.
   - Condition B: 100.
3. Populate 300 lists `l:%04d`. For round in 0..1332, for i in 0..299, send `RPUSH l:i V V V` with V = `b"x"*4500`.
   - That is about 400,000 commands and 5.4 GB. Each list ends with 1333 nodes.
   - Pipeline 300 per send.
4. Fragment: DEL the odd-numbered lists (150 DELs).
   - Check `DEBUG OBJECT l:0000` shows `ql_nodes:1333`.
   - Check `allocator_frag_ratio` is at least 1.3.
5. Probe: `Probe(port, interval=0.00025, cpu=PC)`.
6. Reset counters. Run `CONFIG SET activedefrag yes`, poll INFO until `active_defrag_running` is 0, then stop the probe. This is the same flow as item 1.
7. Alternate arms, 5 repetitions per condition. The defrag window is short (about 0.3 s CPU), so pool the repetitions.

**what to measure**
- PING raw and corrected p50, p99, p99.9 and max in the window.
- Total hits and defrag wall time.
- The optional probe patch from item 1, plus `probe_nodes` and `probe_node_clock` counted in `scanLaterList`. This gives nodes per clock read: about 129 at the parent versus 1 at the fix.

**expected effect**
- Parent slice length is quantised to multiples of a 129-node block (about 0.2 ms), so slices run 0-0.2 ms (up to 0.4 ms for cold 14 KB nodes) past budget.
- Fix overshoot is about 0.003 ms.
- PING p99 at 500 µs: about 0.7 ms versus 0.55 ms. At 100 µs: about 0.3 ms versus 0.12 ms.
- CPU and peak RSS are the same.

**cheap check (about 40 s)**
- Run at 10% scale: 30 lists x 400 rounds. Use 150 lists x 1,333 nodes instead if you need lists above 1000 nodes; 30 lists x 1,333 nodes is the minimum.
- Confirm `ql_nodes` is above 1000 and `active_defrag_hits` is at least 10,000.
- Confirm `allocator_frag_ratio` falls below 1.15.

**risks**
- Effect below noise at default settings.
- Only 50% of nodes move.
- A short defrag window means few informative samples.
- Per-node cost is uncertain (1-3 µs).
- The fix reads the clock once per node, which costs about 20 ns on this tsc clocksource, so it is negligible.
- The parent already has the 512-hit rule, and so does the fix arm, so that rule is not a confound here.

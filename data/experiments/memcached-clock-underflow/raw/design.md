Both designs are below. Item 1 should show in latency. Item 2 is doubtful. I only read code and tools. I built and ran nothing, so every magnitude is my estimate.

Host: 48 CPUs (24 cores x 2 SMT), 128 GB. Run `lscpu -e` and keep server and client CPU sets on disjoint physical cores. Both items need only the Python clients (mcclient.py) plus `taskset`; no memtier/mc-crusher exists on the host. Each fix's parent differs from it only by the lines listed, so the build differences are exactly the bug.

# 1. memcached/clock-underflow

**fix and parent**
- Fix: d7324b0bd108, 2014-04-17 15:59:51 -0700, "fix LRU contention for first minute of uptime".
- Parent (buggy arm): e31a59121031, 2014-04-17 15:27:45 -0700.
- The fix touches items.c, memcached.c and memcached.h only.

**the decision**
- `do_item_update()` decides whether a get hit relinks the item at the LRU head. It compares `it->time` (item's last bump) against `current_time - ITEM_UPDATE_INTERVAL` (60 s). If the item is older, it takes the global `cache_lock` mutex, does `item_unlink_q` + `item_link_q` and sets `it->time`.
- `rel_time_t` is `unsigned int` (memcached.h:207@e31a591). `current_time` starts at 2, so `current_time - 60` wraps to about 4.29e9 until `current_time` reaches 60. The test is then true for every item, so every get hit relinks under the global lock.
- Deciding lines at the parent:
  - items.c:371@e31a591: `if (it->time < current_time - ITEM_UPDATE_INTERVAL) {`, then `mutex_lock(&cache_lock)` at items.c:374.
  - items.c:26@e31a591: `#define ITEM_UPDATE_INTERVAL 60`.
  - memcached.c:191@e31a591: `process_started = time(0) - 2;`.
  - memcached.c:4711@e31a591: `monotonic_start = ts.tv_sec - 2;` (the CLOCK_MONOTONIC path, which is the one used).
- The call chain is `process_get_command` (memcached.c:2977) -> `item_update` (thread.c:572) -> `do_item_update`. `do_item_get` has its `cache_lock` commented out (items.c:546), so a get hit takes only a striped item lock plus the relink lock.
- The fix:
  - Moves the `#define` into memcached.h:71@d7324b0.
  - Makes memcached.c:191@d7324b0 `process_started = time(0) - ITEM_UPDATE_INTERVAL - 2;`.
  - Makes memcached.c:4711@d7324b0 `monotonic_start = ts.tv_sec - ITEM_UPDATE_INTERVAL - 2;`.
  - Makes memcached.c:2565@d7324b0 report `uptime` as `now - ITEM_UPDATE_INTERVAL`, so the uptime stat is identical on both arms.
- `current_time` therefore starts at 62 on the fixed arm and no item is relinked until 60 s after its set.
- The bug window is the first ~58 s of process life. The parent's `uptime` stat equals `current_time`, so the window is `uptime` < 60.

**does it show in latency?** Yes, but only at load and only inside that window.
- With 4 or more workers saturated, the global mutex serialises all relinks. The commit message reports about 350k gets/s capped, against millions after the first minute.
- At light load the uncontended relink costs about 0.1 µs and nothing shows.
- Under closed-loop load, per-request latency scales with the throughput cap (Little's law). Under open-loop load above the buggy cap, latency grows without bound.

**trigger**
- A fresh process (uptime under ~58 s), items already loaded, then many concurrent get hits on at least 4 worker threads.
- Default `-t 4` is enough in principle. `-t 16` makes the global lock the clear bottleneck.
- There is no config knob. The workload must finish before uptime 58.

**workload**

Server start (fresh per run; `taskset` keeps it off the client CPUs):
```
taskset -c 0-15 BIN -p PORT -U 0 -l 127.0.0.1 -t T -m 1024 -o hashpower=20
```
- T=4 is the default (cell A); T=16 is the strong cell B.
- `hashpower=20` avoids a hash-table expansion, which takes `cache_lock`, during load or measurement.

Timeline, in seconds since server start. Assert `stats` uptime at the end of each run is no more than 54.
- t=0 to about 10: load 1,000,000 keys `b"k%07d" % i`, value `b"x"*64`.
  - Use 4 loader processes of 250k keys each, with `MC.set_many` in batches of 1000.
  - Check every reply is `STORED`.
  - Check `stats` has curr_items=1000000, evictions=0 and hash_is_expanding=0.
- About t=15 to 40 (25 s): the measured phase. Start `measure.py --port PORT -- python3 phase.py ...` just before it for server CPU and peak RSS. Optionally run `idleprofile.py --pid PID --seconds 25` beside it for per-thread voluntary context switches.

Clients, N client processes, each pinned to its own CPU with `os.sched_setaffinity` on CPUs 16 and up, one TCP_NODELAY connection each:
- Request: multiget of 64 random existing keys, `b"get " + b" ".join(keys) + b"\r\n"`. The line is under 1024 bytes (64 × 9 B + 4), so it is safe against the pre-newline length check.
- Pre-build 2048 request byte strings per client, with a different seed per client.
- Loop: `t0=perf_counter(); sendall(req); buf=recv(65536)`, then keep receiving until `buf.endswith(b"END\r\n")`, `t1=perf_counter()`. Values are all `x`, so `END\r\n` cannot occur inside a value.
- Count `buf.count(b"VALUE ")==64` on 1 in 1000 responses.
- N=8 for T=4, N=16 for T=16. If the fixed arm's server CPU in a calibration run is not near T cores, raise N.
- Run 1, closed-loop (CL): back-to-back requests. Report keys/s = 64 × requests / 25 s and per-request latency p50, p99 and p99.9.
- Run 2, open-loop (OL): pace each client at R/64/N requests/s on a fixed schedule `due += 1/rate`, never reset, with the last ~100 µs busy-spun.
  - Record both raw and schedule-corrected latency, as `pingprobe._loop` does, and reuse `pingprobe.summary(rows)`.
  - Choose R as the geometric mean of the buggy and fixed CL keys/s (from the first CL reps of each arm).
- Do CL and OL in separate fresh servers, because the window is short.

Repetitions: 4 per arm per cell, alternating (buggy, fixed, buggy, fixed, ...). That is about 50 s per run and about 7 min per cell.

Optional "late" control, 2 runs per arm: start the server, sleep 65 s, then load and run the same CL phase. After uptime 60 the underflow is gone and items are under 60 s old, so the arms should be equal. This shows the difference comes from the underflow and not from some other change.

**what to measure**
- Per-request multiget latency p50, p99 and p99.9 (raw and corrected), and keys/s.
- Server CPU and peak RSS from `measure.py`.
- Decision evidence:
  - The cheap check below, and `stats items` `items:N:age`.
  - Worker voluntary context switches per second from `idleprofile.py`: high on the buggy arm (futex sleeps on `cache_lock`), network-only on the fixed arm.

**expected effect** (a guess, to be confirmed)
- Cell A (T=4, N=8): the fixed arm is client-bound or worker-bound at a few million keys/s. The buggy arm is capped by the global-lock convoy at roughly 0.3 to 1.5M keys/s, so CL latency is about 2 to 5 times higher.
- Cell B (T=16, N=16): the gap should be larger, about 3 to 10 times.
- OL at R between the two caps: the fixed arm stays flat; the buggy arm's corrected latency grows into milliseconds.
- Peak RSS is equal (~170 MB). Server CPU is probably similar or a little higher on the buggy arm.
- The late control should show about 1.0.

**cheap check** (under 1 minute, run at uptime < 40)
```
BIN -p P -U 0 -l 127.0.0.1 -t 4 -o hashpower=20
```
1. Load 10,000 keys `k%07d` with 64 B values.
2. `sleep 5`.
3. Get all the keys once, in descending order (k0009999 first, k0000000 last), in 100 batches of 100 keys.
4. `stats items`: find the class id N from `items:N:number`.
5. `stats cachedump N 1`.

Expected:
- Buggy: the LRU head is `ITEM k0000000 ...` (it was the last item relinked), and `items:N:age` is 0 to 1.
- Fixed: the head is `ITEM k0009999` (last loaded), and `age` is 5 or more.

This proves the workload reaches `do_item_update` with the condition true on one arm and false on the other.

**risks**
- The window is under 58 s. A slow load or a long run falls outside it, so assert the end uptime.
- If the lock is cheap on this CPU (about 50 ns hold plus a spin handoff), the cap could exceed what 8 Python clients can generate. Then raise T and N, or use the OL cell. Python clients top out at roughly 1M keys/s each.
- Connection-to-worker mapping is round-robin. Connect the N clients consecutively with no other connections in between.
- A hash expansion or evictions during the run would add `cache_lock` traffic to both arms. Check `evictions` and `hash_is_expanding`.
- Items loaded at t of about 5 to 10 s on the fixed arm would first relink at t of about 65 to 70 s, which is outside the run.

# 2. memcached/counter-never-decremented

**fix and parent**
- Fix: 917110af97fa, 2016-07-30 22:01:42 -0700, "crawler now uses rate limiter sleeps :(".
- Parent (buggy arm): 117dc8dd1f78, 2016-07-15 09:59:04 -0700.
- The diff is one line in items.c.

**the decision**
- The LRU crawler thread (`item_crawler_thread`) crawls the LRU one item at a time. It is meant to sleep `settings.lru_crawler_sleep` µs (default 100) after every `settings.crawls_persleep` items (default 1000).
- It keeps a local counter `crawls_persleep`, initialised at items.c:1341@117dc8d from `settings.crawls_persleep` (memcached.c:246 sets 1000). The sleep test is:
  - items.c:1403@117dc8d: `if (crawls_persleep <= 0 && settings.lru_crawler_sleep) {`
  - Then `usleep(...)` and the reset at items.c:1405.
- Nothing ever decrements the counter, so it stays at 1000 and the thread never sleeps. It runs flat out for the whole crawl.
- The fix, items.c:1403@917110a: `if (crawls_persleep-- <= 0 && settings.lru_crawler_sleep) {`. That gives one `usleep` per 1001 evaluated items.
- Per item, the crawler does these under `lru_locks[class|LRU]`:
  - `crawler_crawl_q`
  - `hash()`
  - `item_trylock`
  - refcount handling
  - `item_crawler_evaluate`
- The lock is released only after the item is evaluated. Between items the loop scans `crawlers[1..LARGEST_ID]` flags with no lock held.
- Worker sets use the same lock, at least 3 times per overwrite set:
  - `do_item_alloc` calls `lru_pull_tail(id, COLD_LRU, 0, false)` on every alloc when the maintainer is off.
  - `do_item_unlink_q` for the old item.
  - `item_link_q` for the new item.
- Gets do not take `lru_locks`. A set-heavy client therefore feels the crawler; a get-heavy client feels it only through CPU.

**does it show in latency?** Doubtful.
- At the defaults (sleep=100 µs per 1001 items, and `usleep(100)` really takes about 150 µs) the fix lowers crawler duty only from about 100% to about 45% of a core.
- With plentiful CPUs, the crawler holds the class LRU lock about 30 to 40% of the time (my estimate; the flag scan between items is lock-free).
  - The set penalty is a futex sleep/wake on a collision. I estimate that costs a set about 10 µs more on the buggy arm than on the fixed arm.
  - That is 15 to 25% on a Python-measured baseline of 50 to 80 µs, so it could sit inside noise.
- The crawl itself gets faster on the buggy arm. That is the opposite direction, so it can't count as the bug's latency. It is the decision evidence.
- The effect grows when:
  - Sleep is raised: the fixed arm then sleeps long and the buggy arm still ignores it.
  - The server is CPU-confined: an unthrottled crawler takes a share of a scarce CPU.
- A reproduction therefore needs the amplified cells below. It might still come out as "CPU and decision only". An earlier crawler item here (P10) found latency equal.

**trigger**
- `-o lru_crawler` (starts the thread; the maintainer stays off by default at this commit).
- A big LRU, so crawls last long (1M items).
- A crawl restarted continuously, because the thread only walks when asked, via `lru_crawler crawl all` or the maintainer.
- Concurrent sets in the same slab class (L cell) or a CPU-confined server (C cell).
- Optionally `lru_crawler_sleep=1000`, which the fix honours and the parent ignores. doc/protocol.txt:718 documents this knob as "Microseconds to sleep between LRU crawls".

**workload**

Server (fresh per run):
```
taskset -c CPUS BIN -p PORT -U 0 -l 127.0.0.1 -t T -m 1024 -o lru_crawler,lru_crawler_sleep=S,hashpower=21
```
- Drop the `lru_crawler_sleep` option for the default, S=100.
- Cell L (lock contention): CPUS=0-7, T=4.
- Cell C (CPU confinement): CPUS=0-1, T=2.
- Priority order: C at S=1000, L at S=1000, then both again at the default S=100.

Load: 1,000,000 keys `k%07d`, 100 B values, with the same loaders as item 1. This is one slab class of about 192 B chunks, about 190 MB. Check curr_items=1000000 and evictions=0.

Crawl driver (one extra connection, running during the crawl phase only):
```
loop every 2 ms: mc.raw("lru_crawler crawl all") -> b"OK" or b"BUSY ..."; count OKs
```
- The crawler thread holds `lru_crawler_lock` for the whole crawl, so BUSY means a crawl is running.
- This keeps the crawler near 100% active in both arms. Crawl time is about 0.2 to 0.3 s (buggy) and about 0.3 s (fixed, S=100). With S=1000 the fixed arm needs about 1.2 s per crawl.

Phases per run (one server):
- Phase 0, control, 10 s: client load, no crawl commands.
- Phase 1, crawl, 30 s: same client load plus the crawl driver.
- Wrap each phase in `measure.py --port PORT -- ...` for server CPU and peak RSS.
- Run `idleprofile.py --pid PID --seconds 30` during phase 1. The top-CPU thread, near zero in phase 0, is the crawler. Thread names are all "memcached" at this commit.
- Read `stats` before and after each phase for `crawler_items_checked`, `lru_crawler_starts` and `evictions`.

Clients, pinned to CPUs 16 and up:
- Cell L: 8 open-loop set clients.
  - Each does 2,000 sets/s on a fixed schedule (16k/s total), over a random existing key with a 100 B value.
  - Request `set k%07d 0 0 100\r\n<100 x's>\r\n`, then read `STORED\r\n`.
  - Record raw and schedule-corrected RTT, like `pingprobe._loop`.
  - Report p50, p99, p99.9 and mean per phase.
- Cell C: 8 or more closed-loop clients, each doing a 16-key multiget of existing keys back-to-back.
  - Calibrate on the fixed arm with phase 0 only. Pick the smallest client count (4, 8 or 16) at which `measure.py` shows the server at about 1.9 CPUs.
  - Report request p50 and p99 and keys/s per phase.

Repetitions: 4 per arm per cell, alternating. A run is about 60 s, so a cell is about 8 min.

**what to measure**
- Latency: the phase 1 versus phase 0 change (p50, p99, p99.9, mean for sets in L; p50, p99 and keys/s in C), compared across arms. The phase 0 values should be equal across arms, which checks that only the crawler differs.
- Decision counters:
  - `crawler_items_checked` per second (buggy much higher).
  - Crawler thread CPU (buggy about 100% of a core; fixed about 45% at S=100 and about 12% at S=1000).
  - Crawl duration, derived from `lru_crawler_starts` per second.
- Server CPU and peak RSS beside the latency; RSS should be equal.

**expected effect**
- Crawl rate: buggy about 3 to 8M items/s. Fixed is about 0.6 times that at S=100 and about 0.8M items/s at S=1000.
- Cell C, CFS fair sharing with 2 workers plus a crawler on 2 CPUs (a rough model):
  - Buggy: workers get about 67% of a CPU each.
  - Fixed S=100: about 75%, so about 1.1 times lower latency than buggy.
  - Fixed S=1000: about 94%, so buggy latency about 1.4 times higher.
  - At S=1000 this is the most likely cell to show a clear difference.
- Cell L: a small p50 and mean difference, perhaps 5 to 25% at S=1000 and less at S=100. The p99.9 difference may be larger but noisy.
- Control phase 0: equal.

**cheap check** (about 10 s; run for both arms)
```
BIN -p P -U 0 -l 127.0.0.1 -t 4 -o lru_crawler,hashpower=20
```
1. Load 200,000 keys with 100 B values.
2. `lru_crawler sleep 5000` (reply `OK`; runtime change, allowed up to 1,000,000).
3. `t0=time.time(); lru_crawler crawl all` (reply `OK`).
4. Poll `stats` every 5 ms until `lru_crawler_running` is 0. Record the duration and `crawler_items_checked` (should be 200000).

Expected: buggy about 0.03 to 0.1 s (it ignores the sleep). Fixed about 200 × 5 ms, about 1.0 to 1.1 s, which is roughly 15 to 30 times longer. This shows the decision (sleep taken or not) with no client and no timing noise. It also proves the crawler reaches the code and the knob is honoured.

**risks**
- At the default 100 µs setting the throttle changes little. The raters' "unthrottled on LRU locks" effect on request latency may be below Python-client noise, with a per-request baseline of 50 to 80 µs.
- `usleep` rounds up with timer slack, about 150 µs for a nominal 100 µs. The CPU shares above are estimates.
- Cell C only shows when the workers are CPU-saturated. An under-driven server leaves the crawler's CPU free.
- The `lru_crawler_lock` / BUSY logic means the driver must poll quickly, or the crawl duty drops.
- No segmented LRU or maintainer by default at 117dc8d. Do not add `-o modern`; it changes which LRU lock and class are involved.
- If frequency scaling and idle states vary run to run, the baseline can differ by a few µs. Alternate arms and compare the phase 0 versus phase 1 deltas, not absolute values.
- The two commits differ only in the one line, so there are no changed defaults between them.

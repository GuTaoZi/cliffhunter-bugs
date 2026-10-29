# memcached/clock-underflow

- **verdict:** confirmed in latency.
  - In the first minute of uptime, every get hit relinks its item under the global cache lock. Closed-loop 64-key multigets then serve:
    - with 4 worker threads: **2.56M keys/s at p50 202 us**, against the fix's 7.22M at 70 us (2.9x the latency);
    - with 16 worker threads: **2.20M keys/s at p50 245 us and p99 3.6 ms**, against 13.3M at 78 and 96 us (p99 38x).
  - The same phase after 65 s of uptime shows the arms equal (7.24M against 7.23M keys/s, p50 69.5 us both), so the difference is the underflow window.
  - Server CPU is 1.12x (4 threads) and 1.74x (16 threads) higher on the parent for a third of the work. Peak RSS is equal.

- **arms:** parent e31a59121031, fix d7324b0bd108 ("fix LRU contention for first minute of uptime", 2014-04-17).
  - Both are built by `tools/reproduce/build.sh memcached` (-O2, gcc 15.3.0).
  - The 2014 `autogen.sh` needed `AUTOMAKE=automake ACLOCAL=aclocal` to find the installed automake; no code changed.

- **workload:** `run.py measure A 4`, `measure B 4`, `late 2`, with the arms alternating.
  - A fresh server pinned to CPUs 0-7 (cell A, `-t 4`) or 0-15 (cell B, `-t 16`), with 1 GB memory and `hashpower=20`.
  - 1,000,000 keys of 64 bytes, loaded by 4 processes in 1.4 s.
  - From uptime about 3 s, 25 s of closed-loop multigets of 64 random existing keys. There are 8 (A) or 16 (B) client processes, each pinned to its own CPU on other physical cores, with one connection each.
  - Measured: per-request latency; the server's CPU and peak RSS (`tools/reproduce/measure.py`).
  - Every phase ended before uptime 54 s (asserted).
  - **late:** the same after 65 s of uptime.
  - **check:** the LRU head after getting 10,000 keys in descending order.

- **results** (results.md, 4 repetitions per arm per cell, 2 for late):

| cell | measure | parent | fix | parent / fix |
|---|---|---|---|---|
| A (4 threads, 8 clients) | keys per second | 2.56M | 7.22M | 0.35 |
| A | p50 / p99 / p99.9 | 202 / 248 / 261 us | 70 / 84 / 213 us | 2.90 / 2.96 / 1.22 |
| A | server CPU / peak RSS | 94.5 s / 155.9 MB | 84.7 s / 155.9 MB | 1.12 / 1.00 |
| B (16 threads, 16 clients) | keys per second | 2.20M | 13.29M | 0.17 |
| B | p50 / p99 / p99.9 | 245 / 3,613 / 19,130 us | 78 / 96 / 111 us | 3.15 / 37.8 / 172 |
| B | server CPU / peak RSS | 372 s / 156.4 MB | 214 s / 156.4 MB | 1.74 / 1.00 |
| A, after 65 s uptime | keys per second / p50 | 7.24M / 69.5 us | 7.23M / 69.5 us | 1.00 / 1.00 |

  Decision check (`data/check.json`):
  - The parent's LRU head is `k0000000`, the last key got. So every get hit relinked its item.
  - The fix's head is `k0009999`, the last key loaded. So no get relinked.

- **mechanism** (at e31a59121031):
  - `do_item_update` relinks an item when `it->time < current_time - ITEM_UPDATE_INTERVAL` (`items.c:371`, checked), under `cache_lock` (`:374`).
  - `rel_time_t` is unsigned, and `current_time` starts at 2 (`memcached.c:191`, `:4711`). So for the first ~58 s of uptime the subtraction wraps, and every get hit takes the global lock to relink.
  - The fix starts the clock at `ITEM_UPDATE_INTERVAL + 2` (`memcached.c:191,4711@d7324b0bd108`).

- **what did not work:** the first build failed on the 2014 `autogen.sh`, which looks only for automake-1.7 to -1.14 by versioned name. It was fixed in build.sh by naming the installed tools.

- **files:** `run.py`; `data/` (`runs.jsonl`, `check.json`, server logs); `design.md` (verbatim, which also covers memcached/counter-never-decremented); `results.md`.

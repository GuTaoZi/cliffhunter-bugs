# P5 redis/truncated-wait-time — reproduced: an idle server spins before every timer

**Bug.** `aeProcessEvents()` (`src/ae.c`) computed the time to the next timer in microseconds and
then turned it into whole milliseconds by truncating. The loop therefore woke up to 1 ms early,
found no timer due, and called `epoll_wait` with timeout 0 again and again until the timer's
microsecond arrived. Fixed by 175a9e3199f7 (2021-04-13), which keeps microseconds throughout and
rounds up in the epoll backend. The commit says the problem started with the monotonic-timer
change in Redis 6.2.

**Builds:**

| arm | commit |
|---|---|
| buggy | 5e3a15ae1b58, the parent of the fix |
| fixed | 175a9e3199f7 |

Both are `-O2` (`flags.txt`), jemalloc.

**Workload.** A fresh server with no clients. Idle CPU is measured over 30 s with
`tools/reproduce/measure.py` (`run.py`), at the default `hz 10` and at `hz 100`. There are 5 interleaved
repetitions per setting, plus a drift run. A RocksDB benchmark (12 threads, on 48 cores) ran
during part of this. `count_wakeups.py` then runs each arm under `strace`, 10 s idle, twice per
setting, and records every `epoll_wait` call with its timeout.

## Result

Idle server CPU (`summary-hz10.json`, `summary-hz100.json`):

| hz | arm | runs | CPU | peak RSS |
|---|---|---|---|---|
| 10 | buggy | 6 | 0.150% (0.10–0.20) | 6.8 MB |
| 10 | fixed | 5 | 0.033% (all runs) | 6.7 MB |
| 100 | buggy | 6 | 1.26% (1.00–1.93) | 6.8 MB |
| 100 | fixed | 5 | 0.15% (0.07–0.20) | 6.7 MB |

Buggy/fixed is 4.8× (95% CI 3.8–5.8) at hz 10 and 9.3× (4.5–14.1) at hz 100. The values are a few
10 ms ticks per 30 s, close to the resolution of `/proc`. The fixed hz 10 arm read one tick in
every run.

Event-loop waits under strace (`raw/wakeups.jsonl`):

| hz | arm | `epoll_wait` calls/s | of which timeout 0 |
|---|---|---|---|
| 10 | buggy | 24.9–25.9 | 60–62% |
| 10 | fixed | 9.8 | 0 |
| 100 | buggy | 297–307 | 67–68% |
| 100 | fixed | 98.6 | 0 |

The fixed loop waits once per timer tick. The buggy loop adds about 15 (hz 10) or 200 (hz 100)
zero-timeout waits per second. strace makes each call slow, so an untraced server spins more
than this. **The mechanism is confirmed. The cost is small in absolute terms (about 1% of a core
at hz 100) but grows with `hz`.**

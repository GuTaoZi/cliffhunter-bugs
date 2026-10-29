# redis/empty-sample-means-repeat

- **verdict:** confirmed in latency.
  - While a fork child lives and the expires dict has been emptied, the parent's active expire spins its whole time budget on a dict it may not sample. Over 30 s:
    - PING corrected p99 is **25.26 ms** against **0.15 ms**;
    - 238 PINGs exceed 10 ms against 0;
    - the server does not answer for 5.95 s against 0.
  - The expire cycle hits its time cap 10,360 times against 0. Main-thread CPU is 16.5 against 0.53 s.
  - Without the fork child (the control) the dict is shrunk by cron and both arms are flat.
  - Peak RSS is equal.

- **arms:** parent 02a87885e64c, fix f20774eced7e ("Fix active expire timeout when db done the scanning (#13030)").
  - Both are built by `tools/reproduce/build.sh redis` (-O3, gcc 15.3.0, jemalloc).
  - The fix's first build broke at its end, because build.sh was edited while it ran. It was rebuilt from a clean export.

- **workload:** `run.py measure` (4 repetitions per arm, arms alternating) and `run.py control 1`.
  - A fresh server pinned to CPU 2: hz 10, dynamic-hz off, debug command on, `rdb-key-save-delay` 10 s, so a BGSAVE child lives for the whole run.
  - 300,000 keys SET with EX 3600; the expires table has 524,288 buckets.
  - `BGSAVE`, then all but 300 keys deleted, then 3 s to settle. `DEBUG HTSTATS` showed the expires dict stuck mid-rehash in every run.
  - A 30 s window: a PING every 1 ms from its own process (CPU 3), INFO stats deltas, the main thread's CPU, and the server's CPU and peak RSS.
  - **control:** the same without BGSAVE.

- **results** (results.md):

| measure | parent | fix |
|---|---|---|
| PING raw p99 / max | 1.07 / 26.2 ms | 0.08 / 0.55 ms |
| PING corrected p99 | 25.26 ms | 0.147 ms |
| PINGs over 10 ms (of about 30,000) | 238 | 0 |
| unanswered time beyond 1 ms | 5,954 ms | 0 |
| expire cycles that hit the time cap | 10,360 | 0 |
| expire-cycle CPU (INFO) | 16.1 s | 0 |
| main-thread CPU | 16.55 s | 0.53 s |
| peak RSS | 44.3 MB | 43.9 MB |
| control, no fork child: corrected p99 / cap hits | 0.19 ms / 0 | 0.27 ms / 0 |

- **mechanism** (at 02a87885e64c):
  - The loop sets `repeat = data.sampled == 0 || ...` (`src/expire.c:308`, checked) after a `dbScan` that stops at cursor 0 (`:296-299`).
  - A dict with under 1% of its buckets filled is not sampled (`:146-157`; `db.c:1527`). So `sampled` is 0, the loop repeats, and it runs until its time limit: 25 ms per slow cycle, plus fast cycles in beforeSleep.
  - The fork child keeps the resize policy at AVOID, so cron never finishes shrinking the dict.
  - The fix stops when the cursor returns to 0 (`db_done`, `:298-299,313@f20774eced7e`).

- **what did not work:** nothing in the measurement.

- **files:** `run.py`; `data/` (`runs.jsonl`, PING samples gzipped, logs); `design.md` (verbatim, which also covers redis/no-yield-feedback); `results.md`.

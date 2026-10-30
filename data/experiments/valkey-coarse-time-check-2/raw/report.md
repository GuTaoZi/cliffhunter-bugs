# valkey/coarse-time-check-2

- **verdict:** confirmed in latency.
  - When 10,000 hashes of 1,000 fields all expire at the same instant, field expiry on the parent runs past its time slice between clock checks. PING raw p99 over the drain is **26.6 ms** against **2.9 ms**, and corrected p99 is 976 against 35 ms.
  - The largest `expire-cycle` event is 32 against 25.5 ms.
  - The fix pays for this: its drain takes 7.4 against 1.7 s, and it uses 5.6 against 1.9 s of server CPU. Each cycle now stops on time, so there are 2,387 against 287 cycles and more total time without an answer (1.84 against 1.32 s).
  - Peak RSS is equal.
  - The control was meant to show no difference, and it does not hold: one hash of 5,000,000 fields gives the parent expire cycles of 83 ms against 29 ms (see below).

- **arms:** parent cef8822f60b6, fix 3213f48fd694 ("Increase frequency of time check during fields active expiration (#2595)"). Both are built by `tools/reproduce/build.sh valkey` (-O3, gcc 15.3.0).

- **workload:** `run.py measure 4` (arms alternating) and `run.py control 1`.
  - A fresh server pinned to CPU 2: hz 10, effort 1, `latency-monitor-threshold` 2.
  - 10,000 hashes of 1,000 fields with 32-byte values, every field set by `HSETEX ... PXAT T` to expire at the same instant T. The load finishes about 128 s before T.
  - From T-5 s, a PING every 1 ms from its own process (CPU 3), until the database is empty.
  - Measured: latency over [T, drained], INFO stats deltas, `LATENCY HISTORY expire-cycle`, server CPU and peak RSS.
  - **control:** one hash of 5,000,000 fields.

- **results** (results.md, 4 repetitions per arm):

| measure | parent | fix | parent / fix |
|---|---|---|---|
| PING raw p99 | 26.6 ms (15.8-34.0) | 2.86 ms | 9.3 |
| PING raw max | 46.3 ms | 30.4 ms | 1.52 |
| PING corrected p99 | 976 ms | 35 ms | 27.8 |
| largest `expire-cycle` event | 32 ms | 25.5 ms | 1.25 |
| cycles that hit the time cap | 287 | 2,387 | 0.12 |
| drain time | 1.68 s | 7.40 s | 0.23 |
| unanswered time beyond 1 ms | 1.32 s | 1.84 s | 0.71 |
| server CPU | 1.89 s | 5.60 s | 0.34 |
| peak RSS | 1,051 MB | 1,051 MB | 1.00 |
| control (one hash, 5M fields): raw p99 / expire-cycle max | 240 / 83 ms | 32.5 / 29 ms | 7.4 / 2.9 |

  Before T the arms match, at a raw p99 of about 0.1 ms. The 2,000-hash check (`data/check.json`) shows the same shape at a smaller size: raw p99 19.7 against 2.5 ms.

- **mechanism** (at cef8822f60b6):
  - `activeExpireCycleJob` checks its time limit only when `(iteration & 0xf) == 0`: `src/expire.c:392-393`, checked, for key jobs and field jobs alike.
  - A field job's pass can delete many fields, so 16 passes overrun both the fast cycle's 1 ms and the slow cycle's 25 ms.
  - The fix gives field jobs a mask of 0, so they check the clock on every pass (`:221,279,288,400-407@3213f48fd694`).

- **what did not work:**
  - The design's control (one big hash: "one key per pass, no overrun") was wrong. The single hash also overruns, by more (83 ms cycles).
  - Neither arm drained the 5M fields within the 60 s cap (1.86M and 1.79M expired).
  - So the bug does not need many hashes. It needs only many fields due in one pass.

- **files:** `run.py`; `data/` (`runs.jsonl`, `check.json`, PING samples gzipped); `design.md` (verbatim, which also covers valkey/coarse-time-check and sparse-deadline-checks); `results.md`.

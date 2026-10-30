# valkey/coarse-time-check-2

valkey/coarse-time-check-2: field expiry checks the clock every 16 passes and overruns its slice; PING raw p99 26.6 vs 2.9 ms while 10M fields expire, expire cycles 32 vs 25.5 ms; the fix drains 4.4x slower with 3x the CPU; one 5M-field hash overruns too (83 vs 29 ms); peak RSS equal

- **Upstream:** fixed upstream in 3213f48fd694
- **Effect:** latency, strong: 10,000,000 fields expiring together: PING raw p99 26.6 vs 2.9 ms, corrected p99 976 vs 35 ms, expire cycles 32 vs 25.5 ms; the fix drains in 7.4 vs 1.7 s with 3x the CPU; peak RSS equal
- **Experiment:** P48, report: [experiments/reproductions/valkey-coarse-time-check-2/README.md](../../../../experiments/reproductions/valkey-coarse-time-check-2/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 2 free cores; about 2 GB of free RAM

**Build:**

```sh
tools/reproduce/build.sh valkey cef8822f60b6
tools/reproduce/build.sh valkey 3213f48fd694
```

**Run:**

```sh
python3 bugs/systems/valkey/coarse-time-check-2/repro/run.py check
python3 bugs/systems/valkey/coarse-time-check-2/repro/run.py measure 4
python3 bugs/systems/valkey/coarse-time-check-2/repro/run.py control 1
python3 bugs/systems/valkey/coarse-time-check-2/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/*-ping.json.gz, repro/data/check.json, repro/results.md

**Minutes:** about 35

**Notes:** Each run loads 10,000 hashes whose fields all expire 150 s later, then waits for that instant. Port 15476; server on CPU 2, probe on CPU 3. report averages every row of data/runs.jsonl: delete it before a re-run.

## The report

Copied from [`experiments/reproductions/valkey-coarse-time-check-2/README.md`](../../../../experiments/reproductions/valkey-coarse-time-check-2/README.md).

### P48 valkey-coarse-time-check-2 — coarse time check 2

Queue rank 106 of `bugs/tables/queue.tsv` (severity 3, relevance 4.5, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/valkey/coarse-time-check-2/repro/`; raw data: `data/experiments/valkey-coarse-time-check-2/raw/`.

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

## Files

- [`repro/run.py`](repro/run.py)

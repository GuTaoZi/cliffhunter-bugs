# valkey/forced-synchronous-catch-up

valkey/forced-synchronous-catch-up: an insert that asks for a resize mid-rehash finishes the whole rehash at once; after a set's shrink the worst SADD is 63.4 vs 18.9 ms, at the predicted insert; CPU and peak RSS about equal

- **Upstream:** fixed upstream in aefed3d363d1
- **Effect:** latency, strong: after a set's shrink, the insert that asks for a resize finishes the whole rehash: worst SADD 63.4 vs 18.9 ms at the predicted insert; median, CPU and peak RSS about equal
- **Experiment:** P50, report: [experiments/reproductions/valkey-forced-synchronous-catch-up/README.md](../../../../experiments/reproductions/valkey-forced-synchronous-catch-up/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 2 free cores; about 2 GB of free RAM

**Build:**

```sh
tools/reproduce/build.sh valkey dcbaecddce5d
tools/reproduce/build.sh valkey aefed3d363d1
```

**Run:**

```sh
python3 bugs/systems/valkey/forced-synchronous-catch-up/repro/run.py check
python3 bugs/systems/valkey/forced-synchronous-catch-up/repro/run.py measure 4
python3 bugs/systems/valkey/forced-synchronous-catch-up/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/*-lat.json.gz, repro/data/check.json, repro/results.md

**Minutes:** about 10

**Notes:** The exact SREM count matters (run.py's SIZES): fewer does not shrink the table, more leaves the rehash further along. Port 15477; server on CPU 2, probe on CPU 6. report averages every row of data/runs.jsonl: delete it before a re-run.

## The report

Copied from [`experiments/reproductions/valkey-forced-synchronous-catch-up/README.md`](../../../../experiments/reproductions/valkey-forced-synchronous-catch-up/README.md).

### P50 valkey-forced-synchronous-catch-up — forced synchronous catch up

Queue rank 84 of `bugs/tables/queue.tsv` (severity 4, relevance 4, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/valkey/forced-synchronous-catch-up/repro/`; raw data: `data/experiments/valkey-forced-synchronous-catch-up/raw/`.

- **verdict:** confirmed in latency.
  - A set shrunk to the 13% threshold and then refilled makes one SADD on the parent run the whole remaining rehash in one command: **63.4 ms** (56-66), always at command 17,616, the insert the design predicted (1,761,609).
  - The fix's worst command is 18.9 ms, at command 20,971. That is the end of its own step-by-step rehash, when the old table is freed: the design's "comparison floor".
  - The PING probe sees the same: 62.8 against 18.4 ms.
  - Median SADD latency, total time, CPU (2.80 against 2.53 s) and peak RSS (254 against 265 MB) are about equal.

- **arms:** parent dcbaecddce5d, fix aefed3d363d1 ("Don't allow resize hashtable if rehashing is ongoing (#2465)"). Both are built by `tools/reproduce/build.sh valkey` (-O3, gcc 15.3.0).

- **workload:** `run.py check` (2^18 buckets), then `run.py measure 4` (2^21), with the arms alternating.
  - A fresh server pinned to CPU 2.
  - A set S of 10,000,000 string members.
  - Exactly 8,091,592 of them removed with SREM, so the table shrinks at 1,908,408 members and its rehash into the smaller table starts.
  - 2,300,000 new members added by closed-loop SADDs of 100 each, timed per command, with a PING every 1 ms from its own process (CPU 6).
  - The server's CPU (`/proc/PID/stat`) and peak RSS (VmHWM, reset at the phase's start); `DEBUG HTSTATS-KEY S` before and after.

- **results** (results.md, 4 repetitions per arm):

| measure | parent | fix | parent / fix |
|---|---|---|---|
| worst SADD (100 members) | 63.4 ms (56.3-66.1) | 18.9 ms (18.3-19.3) | 3.35 |
| command index of the worst | 17,616 | 20,971 | |
| median SADD | 0.205 ms | 0.204 ms | 1.01 |
| worst PING / unanswered time beyond 1 ms | 62.8 / 64.0 ms | 18.4 / 17.4 ms | 3.41 / 3.68 |
| server CPU | 2.80 s | 2.53 s | 1.11 |
| peak RSS | 253.5 MB | 264.7 MB | 0.96 |

  The 2^18 check (`data/check.json`) shows the decision in the table sizes after the refill:
  - Parent: table 0 is 458,752 and table 1 is 917,504. The shrink's rehash was finished at once, and a growth started.
  - Fix: 1,835,008 and 458,752. Still rehashing step by step.
  - The parent's one slow SADD (10.7 ms) fell at insert 220,200, where the design predicted 220,202.

- **mechanism** (at dcbaecddce5d):
  - When an insert asks for a resize while the table is rehashing, `resize()` runs every remaining step in a loop: `while (hashtableIsRehashing(ht)) rehashStep(ht);` (`src/hashtable.c:629`).
  - The fix refuses a resize while rehashing (`:606,672,1264@aefed3d363d1`).
  - The main keyspace cannot reach this, because cron rehashes it; a set, hash or zset's own table can.

- **what did not work:** nothing.

- **files:** `run.py`; `data/` (`runs.jsonl`, `check.json`, per-command and PING latencies gzipped); `design.md` (verbatim, which also covers valkey/banked-negative-overage); `results.md`.

## Files

- [`repro/run.py`](repro/run.py)

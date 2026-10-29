# valkey/forced-synchronous-catch-up

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

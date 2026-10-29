# P46 valkey-banked-negative-overage — banked negative overage

Queue rank 83 of `bugs/tables/queue.tsv` (severity 3, relevance 5, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/valkey/banked-negative-overage/repro/`; raw data: `data/experiments/valkey-banked-negative-overage/raw/`.

- **verdict:** confirmed in latency.
  - Each restart of active defrag, with data only in db15, gives the parent one main-thread stall of **13.4 ms**. The fix's largest PING is 0.9-2.9 ms.
  - Over 10 restarts, the parent has 10 PINGs over 10 ms against 0, and 121.7 ms against 0.9 ms of unanswered time.
  - The server records the stall itself as a 13 ms `active-defrag-cycle` latency event, which the fix never records.
  - CPU is 1.38 against 1.22 s (1.13x); peak RSS is equal.

- **arms:** parent 1acf7f71c032, fix 0c8ad5cd3412 ("defrag: allow defrag to start during AOF loading (#1420)").
  - Both are built by `tools/reproduce/build.sh valkey`, at Valkey's release default -O3, gcc 15.3.0, with jemalloc.
  - The fix also starts defrag from `defragWhileBlocked`, which this workload never reaches.

- **workload:** `run.py measure 4`, with the arms alternating.
  - A fresh server pinned to CPU 2, with 16 databases and defrag effort pinned at 1% (`active-defrag-cycle-min` and `-max` 1).
  - 2,000,000 keys of 100 bytes, in db15 only (`DEBUG POPULATE`), with every other key unlinked: fragmentation 1.81.
  - A 46 s phase: a PING every 1 ms from its own process (CPU 6), and 10 defrag restarts (`activedefrag yes` for 4 s, then `no` for 0.3 s). Each restart begins a cycle at db0, so it passes 30 empty stages before db15.

- **results** (results.md, 4 repetitions per arm):

| measure | parent | fix |
|---|---|---|
| largest PING | 13.45 ms | 1.91 ms (0.94-2.93) |
| PINGs over 10 ms | 10 (one per restart) | 0 |
| unanswered time beyond 1 ms | 121.7 ms | 0.9 ms |
| largest `active-defrag-cycle` event | 13 ms | none (threshold 5 ms) |
| defrag cycles started | 10 | 10 |
| server CPU | 1.38 s | 1.22 s |
| peak RSS | 320.7 MB | 320.7 MB |

- **mechanism** (at 1acf7f71c032):
  - After each run of the defrag timer, the signed overage is added to a running bank without limit: `src/defrag.c:1179-1180`, checked.
  - The next duty is `P * waited / (100 - P)` minus that bank (`:1158-1161`).
  - An empty stage ends at once and banks almost its whole duty as negative overage. After the 30 empty stages, the first stage with work gets a duty of about 13 ms and runs it in one event-loop call.
  - The fix clamps the bank at 0 (`src/defrag.c:1183@0c8ad5cd3412`).

- **what did not work:** nothing. The check (`data/check.json`) showed the 14 ms event 3 s after enabling defrag, as designed.

- **files:** `run.py`; `data/` (`runs.jsonl`, the PING samples gzipped, logs); `design.md` (verbatim, which also covers valkey/forced-synchronous-catch-up); `results.md`.

# P45 redis-no-yield-feedback — no yield feedback

Queue rank 78 of `bugs/tables/queue.tsv` (severity 3, relevance 5, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/redis/no-yield-feedback/repro/`; raw data: `data/experiments/redis-no-yield-feedback/raw/`.

- **verdict:** confirmed in latency.
  - With fragmentation the scan cannot move, the parent keeps active defrag at its full effort (50%) for ever. Steady-state PING corrected p99 is **48.7 ms** on the parent against **2.1 ms** on the fix, whose effort decays to 2%.
  - Main-thread CPU in steady state is 31% of a core against 4%. Server CPU over the 80 s run is 24.9 against 5.9 s. Peak RSS is equal.
  - In the first 10 s, before the fix's decay has acted, the arms are alike (48.8 against 39.6 ms), as designed.

- **arms:** parent dcd0b3d02013, fix f86575f210a9 ("Gradually reduce defrag CPU usage when defragmentation is ineffective (#13752)").
  - Both are built by `tools/reproduce/build.sh redis` (-O3, gcc 15.3.0, jemalloc).
  - The `datatype` test module is built from each arm's own tree.

- **workload:** `run.py measure 4`, with the arms alternating.
  - A fresh server pinned to CPU 2: hz 10, dynamic-hz off, one database, the module loaded, verbose log.
  - 200,000 `DATATYPE.SET` values of 400 bytes, with every even key deleted. Module values without a defrag callback cannot be moved, so fragmentation stays at 1.95.
  - Defrag thresholds are set from the measured fragmentation F: lower 1, upper 0.9 F, cycle-min 1, cycle-max 50.
  - 80 s with `activedefrag yes` at t=0, a PING every 1 ms from its own process (CPU 3), and INFO once a second.

- **results** (results.md, 4 repetitions per arm):

| measure | parent | fix | parent / fix |
|---|---|---|---|
| defrag effort, `active_defrag_running`, [45,75) s | 50% | 2.0% | |
| PING corrected p99, [45,75) s | 48.69 ms | 2.07 ms | 23.5 |
| PING corrected p99, [0,10) s (first passes, a control) | 48.82 ms | 39.58 ms | 1.23 |
| main-thread CPU, [45,75) s | 0.313 cores | 0.041 cores | 7.6 |
| server CPU, whole run | 24.89 s | 5.90 s | 4.2 |
| peak RSS | 118.2 MB | 118.2 MB | 1.00 |

  The pass log shows the decision.
  - The parent starts each pass with `cpu=50%`, does it in about 127 ms with `reallocated=0`, and starts again at 50%.
  - The fix's effort steps down by 0.9 per pass (`data/check.json`, results.md).

- **mechanism** (at dcd0b3d02013):
  - `computeDefragCycles` sets the effort from the current fragmentation alone and stores it: `server.active_defrag_running = cpu_pct`, `src/defrag.c:1053`, checked.
  - `activeDefragCycle` spends `running` percent of each 100 ms tick on the main thread (`:1122`).
  - At each pass end the effort is recomputed from fragmentation again (`:1160-1164`). Hits and misses are never looked at.
  - The fix multiplies a `decay_rate` into the effort (`:1044@f86575f210a9`), times 0.9 after a pass that changed fragmentation by 2 points or less with under 1% hits (`:1166-1181`).

- **what did not work:** nothing.

- **files:** `run.py`; `data/` (`runs.jsonl`, the per-second series and PING samples gzipped, pass logs); `design.md` (verbatim, which also covers redis/empty-sample-means-repeat); `results.md`.

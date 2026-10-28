# P25 valkey-blind-to-target-overload — inserts during a hashtable shrink chain in the tiny new table

Queue rank 12 of `bugs/tables/queue.tsv` (severity 4, relevance 5, two raters). Reproduced on 2026-10-27 in the main session; the report follows. Code: `bugs/systems/valkey/blind-to-target-overload/repro/`; raw data: `data/experiments/valkey-blind-to-target-overload/raw/`.

Queue rank 12 of `bugs/tables/queue.tsv` (severity 4, relevance 5, cost low; two raters). Reproduced on 2026-10-27 in the main session (`run.py`, `session.sh`).

**The bug.** In Valkey's hashtable (`src/hashtable.c`), when a large table shrinks, every new entry goes into the new, small table (ht1) and expansion is blocked until the rehash ends. If the old table (ht0) is huge and nearly empty, its rehash is slow (mostly empty buckets), so a burst of inserts overfills the tiny ht1 into long chains of child buckets. Fixed upstream in 262b371da0d2 (#3175, 2026-02-24): during a shrink, an insert checks ht1's fill and above the hard maximum swaps the tables, aborts the shrink and rehashes as an expand.

**Arms.** Parent 501b3153f26e against the fix 262b371da0d2, release builds (`tools/reproduce/build.sh`), fresh server per run (`--save "" --appendonly no --enable-debug-command yes`), port 15426. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (the fix's own test, `tests/unit/type/zset.tcl`, larger): one sorted set filled with 2,000,000 members (pipelined `ZADD` batches of 1,000); `ZREMRANGEBYRANK z 1 -1` deletes all but one member in a single command; then, measured, a burst of 200,000 new members in pipelined `ZADD` batches of 100, timing each batch, with server CPU and peak RSS over the burst (`tools/reproduce/measure.py`'s Sampler) and `DEBUG HTSTATS-KEY` before and after. (A first version deleted members one `SREM` at a time; each removal advanced the rehash, the shrink finished before the burst and nothing showed: that run is kept aside, `data/runs-first-version-srem.jsonl`, and not counted.)

**Results** (mean, sd over 5 runs per arm; `results.md`):

| over the burst of 200,000 inserts | parent | fix | parent / fix |
|---|---|---|---|
| p99 latency of a 100-insert batch | 2.52 ms (sd 1.1) | 0.47 ms (sd 0.03) | 5.4 |
| worst batch | 4.54 ms | 1.65 ms | 2.8 |
| median batch | 0.386 ms | 0.377 ms | 1.0 |
| burst wall time | 1.24 s (sd 0.19) | 0.97 s (sd 0.005) | 1.28 |
| server CPU | 0.54 s (sd 0.19) | 0.27 s (sd 0.008) | 2.0 |
| peak RSS | 167.7 MB | 167.8 MB | 1.0 |

The table state confirms the mechanism. Before the burst, in both arms: ht0 with 524,288 top-level buckets holding 1 entry, rehashing index 0, and the target ht1 of 7 entries (1 bucket). After it: the parent's table has 32,768 buckets with 8,949 child buckets (chains), built while every insert went into the tiny ht1; the fix aborted the shrink, keeping the 524,288-bucket table with no child buckets. A replicate set run without the table statistics (`results-without-debug-stats.md`) gave the same picture: p99 6.6x, server CPU 2.1x.

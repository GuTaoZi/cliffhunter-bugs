# P17 postgres-omitted-memory-cost — hash-join batch growth ignores batch-file memory

Queue rank 1 of `bugs/tables/queue.tsv` (severity 4.5, relevance 5, two raters). Reproduced on 2026-10-22 by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`); its report follows, as returned. Code: `bugs/systems/postgres/omitted-memory-cost/repro/`; raw data: `data/experiments/postgres-omitted-memory-cost/raw/` (not copied, too large: d/ (5020 MB); they stay in the data root's repro/ directory).

Measured 2026-10-22, 21:38–21:56 EDT, every run under the machine lock.

## Verdict
**Confirmed.** The parent of the fix keeps doubling the hash join's batch count without counting the 8 KiB buffer that every batch file carries. Main workload (variant A):
- **Batches:** 128 → 262,144 in the parent, against 8 → 128 with the fix.
- **Memory:** 1.59 GB private in the parent (2.9 GB allocated for batch files), against 7.2 MB.
- **Time:** about 23x the latency and about 60x the CPU.
- **Scaling:** all of it doubles when the data doubles (variant E).

Two caveats:
- **The miner's literal hint does not reproduce the harm.** One key repeated 10M times and nothing else cannot explode, because growth turns off at the first doubling (variant C).
- **The size of the harm depends on where the duplicate group sits** (variants B and D).

## Arms
| arm | commit | build dir | flags |
|---|---|---|---|
| parent | 8b886a4e3488 | $CLIFF_DATA/build/postgres-8b886a4e3488 | -O2 on every compile line, gcc 15.3.0, no USE_ASSERT_CHECKING |
| fix | a1b4f289beec | $CLIFF_DATA/build/postgres-a1b4f289beec | same |

- Both were built with `flock …/machine.lock sh tools/reproduce/build.sh postgres <sha>`.
- The fix changes only src/backend/executor/nodeHash.c (+129 lines). BLCKSZ is 8192.

## Workload
`workload.py`, driven by `run_all.sh`, runs one serial hash join.

**Query:** `SELECT count(*) FROM outer_t o JOIN inner_t i ON o.k=i.k`, run as `EXPLAIN (ANALYZE, TIMING OFF, COSTS OFF)` so every repetition also reports batch counts.

**Session settings:**
- `work_mem=64kB`, `hash_mem_multiplier=2.0`
- `enable_mergejoin=off`, `enable_nestloop=off`
- `max_parallel_workers_per_gather=0`

**Server:** `shared_buffers=128MB`, `autovacuum=off`, `fsync=off`, Unix socket only. Ports: parent 15420, fix 15421.

**Tables:**
- The hashed table `inner_t` has N distinct keys plus D copies of one key.
- The probe table `outer_t` has M distinct keys, none matching the duplicate key.
- Both are VACUUM FREEZEd (the planner knows the row counts) but never ANALYZEd (it does not know about the duplicates).
- Both plans hash `inner_t`.

**Variants:**
- **A (main):** N=200k, D=100k, M=600k. Distinct keys are stored first, the duplicates last. The duplicate key is -57267: its hash is 698 (bits 10–31 zero), so the group stays in the batch being built.
- **E:** A with every table doubled.
- **D:** A with the rows shuffled.
- **B:** A with an ordinary key, 0.
- **C:** the hint literally: 10M copies of key 0 and nothing else, M=12M.

**Measurement:**
- Repetitions are interleaved with alternating order, after one warm-up per arm. A, B and D have 5 repetitions per arm; C and E have 3.
- Each run is `tools/reproduce/measure.py --pid <postmaster> -- psql …`: wall time, CPU of the whole server tree, peak VmHWM.
- A 20 ms sampler records the largest private memory (RssAnon) in the tree.
- The temp-file count for each run comes from `pg_stat_database`.

**Commands** (in the repro directory):
- `flock $CLIFF_DATA/locks/machine.lock sh run_all.sh A B`
- `flock …/machine.lock sh run_all.sh D E C`
- `flock …/machine.lock python3 diag_ctx.py …` (memory-context dump, one run per arm)
- `python3 summarize.py A E D B C`

## Results
Mean ± stdev [min, max]; the last column is parent/fix, paired by repetition.

**A (main), 5 vs 5 repetitions**
| metric | parent | fix | ratio |
|---|---|---|---|
| wall (s) | 7.66 ± 0.32 [7.35, 8.01] | 0.334 ± 0.294 [0.115, 0.689] | 43.8 [10.7, 70.0] |
| server CPU (s) | 6.69 ± 0.05 | 0.112 ± 0.016 | 60.7 [47.4, 67.5] |
| peak RSS, VmHWM (MB) | 1,635 ± 0.0 | 49.6 ± 0.0 | 33 |
| peak private memory, RssAnon (MB) | 1,592 ± 0.0 | 7.2 ± 0.0 | 221 |
| batches, planned → at end | 128 → **262,144** | 8 → 128 | |
| temp files | 375,126 | 254 | |
| temp blocks read / written | 280,047 / 375,637 | 2,959 / 2,959 | |
| temp file bytes | 22.9 MB | 22.3 MB | |
| hash table (EXPLAIN Memory Usage) | 3.5 MB | 4.1 MB | |
| batch-file memory (HashSpillContext), largest seen | 2,933 MB in 368,474 blocks | 0.1 MB (one poll; the run lasts 0.1 s) | |

Two of the fix's repetitions took 0.62 and 0.69 s of wall time with unchanged CPU, so they were waiting on I/O. CPU is the stable measure.

**E (A doubled), 3 vs 3:** the parent doubles on every measure; the fix grows from 7.2 to 12.6 MB.
- wall: 17.83 ± 0.42 s vs 0.244 ± 0.001 s (73x)
- CPU: 13.84 vs 0.223 s
- VmHWM: 3,262 vs 86.6 MB
- RssAnon: 3,188 vs 12.6 MB
- batches: 256 → **524,288** vs 8 → 256
- temp files: 751,239 vs 510

**D (shuffled), 5 vs 5:**
- wall: 0.692 ± 0.006 s vs 0.120 ± 0.001 s (5.8x)
- CPU: 0.664 vs 0.096 s
- VmHWM: 206 vs 50.7 MB
- RssAnon: 163 vs 8.2 MB
- batches: 128 → 16,384 vs 8 → 128
- temp files: 32,766 vs 254

**B (key 0), 5 vs 5:**
- wall: 0.171 vs 0.137 s (1.3x)
- CPU: 0.148 vs 0.114 s
- VmHWM: 50.9 vs 47.1 MB
- RssAnon: 4.3 vs 4.7 MB
- batches: 128 → **262,144** vs 8 → 128
- temp files: 980 vs 30

**C (hint literally), 3 vs 3:**
- wall: 3.03 ± 0.07 s vs 2.63 ± 0.004 s (1.15x)
- CPU: 2.92 vs 2.60 s
- VmHWM: 541 vs 556 MB
- RssAnon: 400 vs 416 MB
- batches: 8,192 → 16,384 vs 8 → 16
- hash table: 351.6 MB in both

In every run, both arms return the same join row counts. No run failed or wrote to stderr.

## Mechanism
**Parent 8b886a4e3488:**
- The planned batch count is based only on the size of the in-memory hash table (nodeHash.c:845-848@8b886a4e3488).
- At run time, inserting a tuple past the memory limit calls ExecHashIncreaseNumBatches (nodeHash.c:1678-1681@8b886a4e3488), which doubles the batch count unconditionally (nodeHash.c:916@8b886a4e3488).
- The only brake stops growth when a doubling moves none or all of the in-memory tuples (nodeHash.c:1047-1049@8b886a4e3488).
- In A, each doubling still moves about half of the roughly 1,500 distinct tuples that share batch 0 with the duplicate group. So it doubles about 11 times, to 262,144 batches.
- Each batch then gets a batch file per side, created lazily (nodeHashjoin.c:1437@8b886a4e3488). The probe side's rows are routed into them (nodeHashjoin.c:494-496@8b886a4e3488).
- Each file embeds an 8 KiB buffer (`PGAlignedBlock buffer`, buffile.c:103@8b886a4e3488).
- Result: about 370k files open at once, 2.9 GB allocated (1.59 GB resident, since one-tuple files touch only part of their buffer), and 375k block writes for 23 MB of data. The hash table itself is 3.5 MB.

**Fix a1b4f289beec:**
- At planning, a new loop (nodeHash.c:913-933@a1b4f289beec) halves the batch count while that lowers hash-table plus file-buffer memory: 128 → 8 in A.
- At run time, ExecHashIncreaseBatchSize (nodeHash.c:992-1016@a1b4f289beec, called at :1042) doubles the memory allowance instead of the batch count once the allowance is ≤ nbatch·2·BLCKSZ. Batches stop at 128 and the duplicate group fits in a 4.1 MB table.

## What did not work, and caveats
- **The literal hint (C) does not show the harm.** With only one key, the first doubling moves all or none of the tuples and growth turns off (nodeHash.c:1047@8b886a4e3488). The 1024x batch-count gap comes only from planning (8,192 vs 8), and the 352 MB duplicate group that both arms must hold dominates memory. The explosion needs the group to share its batch with distinct keys.
- **The harm depends on where the group sits.**
  - With key 0 (B), the group has left batch 0 before the build overflows. It explodes only when its own batch is reloaded, when few tuples remain to spread. Batches still reach 262,144, but only 980 files are created and memory is equal.
  - The gigabyte case (A, E) needs the group to stay in the batch being built while the probe side is still to be split. Key -57267 was chosen for that; about one key in 2^z stays in batch 0 through z doublings.
  - Shuffling the rows (D) stops growth sooner.
- **Planner MCV check left out on purpose:** with ANALYZE, the planner's MCV check (costsize.c:4409@8b886a4e3488) would discourage this hash join, so the tables were left unanalyzed, matching the bug reports.
- **VmHWM includes shared buffers** (about 30 MB, the same in both arms); RssAnon is the private-memory figure.
- **Smoke tests:** done at 1/10 scale on the existing unfixed build postgres-9878b643f37b (port 15429) and on both arms; they are in results/smoke.jsonl and not used in the results.

## Files
Scripts (`workload.py`, `run_all.sh`, `summarize.py`, `diag_ctx.py`) are in the bug's `repro/` directory. Raw records (`results/{A,B,C,D,E}.jsonl`, `results/summary.md`, `results/smoke.jsonl`) and the EXPLAIN output of every run (`logs/`) are in the raw-data directory. The data directories and server logs (`d/`, about 5 GB) stay in the data root.

# MongoDB latency bugs for trace analysis

Exported from the study's `docs/trace-candidates-mongodb.md`; the measurements are the bugs' own runs in this kit, linked from each bug's README.

Six bugs from the MongoDB set in `bugs/index.tsv`, chosen for a trace-analysis method that:
- injects counters and timers into code blocks;
- tracks how their timings vary across requests and runs;
- correlates callers' timings with their callees' to find the hotspot.

Each bug is described below with its measured latency, CPU and peak memory, where the time goes, and where to put
counters and timers. Bugs whose cost is memory, or that show no latency difference, are listed at the end with the
reason they were left out.

## Contents

- [Measurement setup](#measurement-setup)
- [Summary](#summary)
- [The plan cache: shared code](#the-plan-cache-shared-code) (bugs 1–3)
- [1. SERVER-79039](#1-server-79039-continuous-replanning-of-one-plan)
- [2. SERVER-107471](#2-server-107471-a-skip-poisons-the-replan-threshold)
- [3. SERVER-32452 (W5)](#3-server-32452-w5-an-expensive-query-makes-wrong-plans-permanent)
- [4. Hash-join eligibility (W2)](#4-hash-join-eligibility-bound-w2)
- [5. SERVER-14034 (W1)](#5-server-14034-w1-explode-for-sort-cap)
- [6. SERVER-14423 (W4)](#6-server-14423-w4-the-101-result-trial-period)

The bugs fall into two groups, which need different analyses:

| group | bugs | what varies | where the decision runs |
|---|---|---|---|
| **order-dependent** (the plan cache) | 1, 2, 3 | The same queries, submitted in a different order, give different latencies. Within one run, queries of the same shape split into fast and slow groups. | At execution time: the deciding loop calls the costly code, so caller and callee nest. |
| **threshold steps** | 4, 5, 6 | Latency jumps when an input crosses a fixed bound, and is flat on either side. | At planning time: the costly code runs later, in the execution tree the decision chose. |

## Measurement setup

These facts hold for all six bugs unless a section says otherwise.

- **Server.** MongoDB 8.2.12, a prebuilt release binary.
  - `internalQueryFrameworkControl=trySbeRestricted`, the default multi-planner ranker, and every plan-cache
    setting at its default (`internalQueryCacheEvictionRatio=10`, `internalQueryPlanEvaluationMaxResults=101`).
  - WiredTiger cache 8 GB.
- **Host.** Intel Xeon 6521P, 48 cores, 125 GB, Linux 6.18.51
  (`env.md` of experiment N3; `experiments/INDEX.md` lists every experiment's directory by its ID).
- **Latency** is wall-clock time per query, taken at the client (mongosh on the same host) around each query, with
  `CH.timeNs` in `tools/harness/lib.js`.
  - For bugs 1–3 the per-query records (`trace[].wall_ms`) are kept, so the percentiles below were computed from
    them.
  - For bugs 4–6 each point is the median of repeated runs.
  - "Server ms" is the server's own time for the operation, from the database profiler.
- **CPU and peak memory** are for the `mongod` process alone, which ran in its own cgroup.
  - Peak memory is sampled from `memory.current`.
  - It is dominated by the 8 GB WiredTiger cache, so anything allocated per query below a few MB is under the
    measurement floor.
- **Noise floor.** 30 repeats of one W1 point (k=100) gave a median of 3.84 ms, p10–p90 3.50–4.27 ms
  (`experiments/cliffs/2026-09-15-w1-explode-for-sort/noise-floor.jsonl`). Every difference below is far above this.
- **Code locations** are cited as `path:line@6d990baca59c`, in MongoDB master at that commit, not in the 8.2.12 tag.
  Differences that matter are noted where they apply.
- **Finder marks.** Some cited lines carry a mark from this project's finder (`tools/finder/`, run on
  6d990baca59c). The finder labels a branch "heuristic" when it compares a measured, kept value with a bound and
  its own code changes that value; the other labels mean it does not. Branches labelled heuristic are natural places
  for a counter.

## Summary

| # | bug | latency, buggy vs healthy | CPU, buggy vs healthy | peak memory | what varies | fit |
|---|---|---|---|---|---|---|
| 1 | [SERVER-79039](https://jira.mongodb.org/browse/SERVER-79039) | expensive queries p50/p99 68.1/133.5 vs 28.8/78.6 ms | 1,767.2 vs 819.0 ms per run | 3,447.5 vs 3,420.7 MB | arrival order | strong |
| 2 | [SERVER-107471](https://jira.mongodb.org/browse/SERVER-107471) | rare queries p50/p99 22.6/38.3 vs 1.9/2.4 ms | 488.7 vs 294.8 ms per run | 2,717.1 vs 2,717.2 MB | arrival order; one query's `.skip()` | strong |
| 3 | [SERVER-32452](https://jira.mongodb.org/browse/SERVER-32452) (W5) | affected queries p50/p99 384.3/392.0 vs 2.6/3.7 ms | 10,892.7 vs 1,716.0 ms per run | 2,382.8 vs 2,382.5 MB | arrival order | strong |
| 4 | hash-join eligibility (W2) | 11.41 → 2,479.86 ms (217×) | 19.1 vs 2,758.4 ms per query | not reliably measured (see §4); the hash table is under 1 MB | foreign collection size, 10,000 → 10,001 | strong (a step) |
| 5 | [SERVER-14034](https://jira.mongodb.org/browse/SERVER-14034) (W1) | 4.61 → 359.51 ms (78×) | 0.00 vs 2.17 s per 5 queries (own build) | 471.4 MB (own build, whole run) | `$in` list length, 200 → 201 | strong (a step) |
| 6 | [SERVER-14423](https://jira.mongodb.org/browse/SERVER-14423) (W4) | median 1,418.7 vs 25.6 ms | 1,524.8 vs 85.2 ms per query | 2,182.9 vs 2,183.4 MB | the trial-period setting and the data layout | medium |

Where the time goes, in brief:

| # | decision (a counter goes here) | where the extra time is spent |
|---|---|---|
| 1 | `CachedPlanStage::pickBestPlan` trial loop, `cached_plan.cpp:87` | `MultiPlanStage::runTrials`, re-run on almost every expensive query |
| 2 | the same trial loop | the cached plan's index scan and fetch, run to the end inside the trial loop |
| 3 | the same trial loop | the same, for the class the cached plan is wrong for |
| 4 | `isEligibleForHashJoin`, `planner_analysis.cpp:950` | `LoopJoinStage::getNext` and `openInner`, once per local document |
| 5 | `explodeForSort`, `planner_analysis.cpp:1366` | `SortStage::doWork` pulling a long `IndexScan::doWork`, instead of `MergeSortStage` |
| 6 | `MultiPlanStage::workAllPlans`, `multi_plan.cpp:556` | `FetchStage::doWork` over the chosen plan's index scan, after planning ends |

## The plan cache: shared code

Bugs 1–3 are the same machinery failing in different ways. Each query shape has one plan cache entry, which stores
a plan and a `works` value (how much work that plan took when it was chosen). All three bugs come from the rule that
updates `works`, and from the loop that reads it.

| step | code (`src/mongo/db/...@6d990baca59c`) | what it does |
|---|---|---|
| look up the cache | `query/get_executor.cpp:697` `buildCachedPlan` (miss counted at :710, hit at :714, cached planner built at :717) | a hit runs the cached plan through a trial, below |
| cached trial | `exec/classic/cached_plan.cpp:59` `CachedPlanStage::pickBestPlan` | the decision point for all three bugs |
| replan bar | `cached_plan.cpp:75-76` | `maxWorksBeforeReplan = internalQueryCacheEvictionRatio (10) × works` |
| trial loop | `cached_plan.cpp:87` `for (i = 0; i < maxWorksBeforeReplan; ++i)` | finder: **heuristic** |
| one unit of plan work | `cached_plan.cpp:97` `child()->work(&id)` | where the cached plan's execution time accrues during the trial |
| enough results | `cached_plan.cpp:122` | finder: **heuristic**; the plan is kept |
| plan finished | `cached_plan.cpp:127` | IS_EOF: the plan is kept and never replanned |
| bar exceeded | `cached_plan.cpp:162` → `replan()` at :185 | discards the trial and plans again |
| plan again | `exec/classic/multi_plan.cpp:269` `MultiPlanStage::runTrials` (trial loop :326, planner metrics :372); `pickBestPlan` :434 | runs every candidate plan, round-robin |
| one round of all candidates | `multi_plan.cpp:504` `workAllPlans`; stop on a full batch or end at :556 (finder: **heuristic** at column 56); first plan to finish wins at :568 | |
| update the entry | `query/plan_cache/plan_cache.h:675` `getNewEntryState`: active entry left alone at :717; `works` raised to `max(works+1, works×2)` at :733; a cheaper plan promotes the entry and *sets* `works` at :750 | finder: **heuristic** at :709 and :724 |
| trial result target | `exec/trial_period_utils.cpp:37-48` `getTrialPeriodNumToReturn` | `min(limit, internalQueryPlanEvaluationMaxResults)`; a `skip` does not count |

Two things make this machinery a good target for timers:

- **The decision and its cost nest.** The trial loop at `cached_plan.cpp:87` calls the plan's `work()` at :97. A
  cached plan that finishes within the bar runs the whole query inside the trial. A plan that exceeds it goes to
  `replan()`, which runs `MultiPlanStage::runTrials`. A timer on `pickBestPlan` and timers on its two callees split
  each query's latency into "ran the cached plan" and "planned again".
- **Per-query counters cannot see it.** A replan throws its trial away and runs the query again from a fresh
  executor, so the discarded work is attributed to no operation. Documents examined can be identical across orders
  that differ 2× in latency (bug 1). Only server-wide counters (`multiPlanner.classicMicros` and
  `classicWorks` in `serverStatus`) carry the cost, and they cannot be traced to a query.

**Version difference.** In master at 6d990baca59c, `replan()` throws `ReplanningRequired`, which
`query/get_executor_helpers.cpp:209` catches. Its loop at :159 (finder: **heuristic**) then plans again. In 8.2.12
the replan is expected to happen inside `CachedPlanStage`, so call stacks will differ from the lines cited here.

## 1. SERVER-79039: continuous replanning of one plan

**Ticket.** [SERVER-79039](https://jira.mongodb.org/browse/SERVER-79039), *"Plan cache entries can be evicted and
replanned continuously for certain workload patterns"*, filed 2023-07-17, closed Won't Do 2023-08-17, reason "changes
to the replanning behaviour are too risky".

**What goes wrong.** Two classes of one query shape use the same plan; only how much work it costs differs.
- 1,000,000 documents, indexes `{a:1}` and `{b:1}`, shape `find({a:<int>, b:0})`.
- Cheap class C: `a` in 1..1000, 5 results, 6 works.
- Expensive class E: `a: 900001`, 3 results, 50,001 works.
- 48 queries per run (6 C and 6 E per epoch, four epochs); only their order differs between runs.

When the queries alternate, the entry's `works` never settles:
1. C promotes the entry and *sets* `works` to 6 (`plan_cache.h:750`).
2. E then runs the cached plan against a bar of 10 × 6 = 60 works and exceeds it at `cached_plan.cpp:87`.
3. E replans, which doubles `works` to 12 (`plan_cache.h:733`).
4. The next C sets it back to 6.

`works` reads `[6, 12, 6, 12, …]` for all 48 queries and never reaches E's real cost of 50,001. When the E queries
come first, the entry settles at 50,001 and almost nothing replans. Every replan picks the plan that was already
cached (`planCache.classic.replanned_plan_is_cached_plan` equals `replanned` in every order).

**Measurements** (experiment N3: `s79039-report.txt`, `s79039-resources.txt`, `s79039.jsonl`):

| order | E p50 / p99 | C p50 / p99 | server ms | multi-planner µs | replans | CPU ms | wall s | peak RSS MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **alternating** | **68.1 / 133.5** | 1.8 / 3.6 | 1,715 ± 18 | **1,722,968** | **23** | 1,767.2 | 2.5 | 3,447.5 ± 35.1 |
| blocked_CE | 67.6 / 110.7 | 1.5 / 2.0 | 1,634 ± 49 | 1,641,589 | 4 | 1,778.8 | 2.5 | 3,422.4 |
| **blocked_EC** | **28.8 / 78.6** | 1.5 / 1.7 | **766 ± 43** | **139,714** | **0** | **819.0** | **1.6** | 3,420.7 |
| shuffled | (not traced) | (not traced) | 1,617 ± 30 | 1,623,640 | 11 | 1,769.5 | 2.5 | 3,419.4 |

- **Documents examined: 1,200,120 in every order (1.0×).** The server-wide `queryExecutor.scannedObjects` is also
  identical across orders.
- The multi-planner ran 48 times in the alternating order and 2 times in blocked_EC.
- Peak memory: one alternating repeat read 3,497 MB; the others 3,419–3,423 MB.
- The threshold is exact. E is stable with 59 matching documents (60 works, not above the bar of 60) and replans
  continuously with 60 (61 works).

**What timers should show.**
- In the buggy orders, most E queries run the cached plan for 60 works, then replan, so their time lands in
  `MultiPlanStage::runTrials` (`multi_plan.cpp:269`).
  - That trial runs every candidate plan, so it does the query's work plus the losing candidate's.
  - This fits E taking about twice as long (68.1 vs 28.8 ms p50) while documents examined stay the same.
- In blocked_EC, E's time is the cached plan's own `work()` under `cached_plan.cpp:97`, and `runTrials` runs twice
  in 48 queries.
- Class C is 1.5–1.8 ms in every order: a built-in control for the method.

These are expected from the mechanism. What was measured is per-query latency, per-run server time, multi-planner
time and replan counts.

**Where to put counters and timers.**
- Counters: iterations of the loop at `cached_plan.cpp:87`; calls to `replan()` (:185); the `works` value written at
  `plan_cache.h:733` and :750.
- Timers: `CachedPlanStage::pickBestPlan` (caller), the `child()->work()` call at :97 (callee during the trial), and
  `MultiPlanStage::runTrials` (callee after a replan).
- Correlation to look for: runTrials time against E's latency, high in the alternating order and near zero in
  blocked_EC. This bug is the best test of the method, because the standard per-query metrics show nothing.

## 2. SERVER-107471: a `.skip()` poisons the replan threshold

**Ticket.** [SERVER-107471](https://jira.mongodb.org/browse/SERVER-107471), *"Query Plan Cache Issue with Index
Selection on High Disparity Index Values"*, filed 2025-07-14 against 4.4, closed Won't Do 2025-08-20, reason "4.4
is end-of-life, retest on v7.0+". The behaviour was measured on 8.2.12.

**What goes wrong.** `skip` and `limit` are not part of the plan cache key, so a paginated query and a plain query
share one entry.
- 1,000,000 documents, indexes `{indexField1:1}` and `{indexField10:1}`.
- Paginated class P: `find({indexField1:7, indexField10:0}).skip(5000).limit(10)`. It picks
  `IXSCAN{indexField1}`, and its trial takes 5,274 works.
- Rare class R: `find({indexField1:7, indexField10:93333+k}).limit(10)`. It matches one document.
  - Right plan `IXSCAN{indexField10}`: 1 read.
  - Wrong plan `IXSCAN{indexField1}`: 20,000 reads.

The trial's result target ignores the skip (`trial_period_utils.cpp:37-48`), so every skipped document costs a work
unit and yields no result. When P is cached first, it sets the replan bar to 10 × 5,274 = 52,740 works. R's wrong
plan costs only 20,001, which is under the bar, so it runs to the end inside the trial loop and is never replanned:
24 times out of 24, with zero replans.

**Measurements** (experiment N3: `s107471-report.txt`, `s107471-resources.txt`, `s107471.jsonl`):

| order | R p50 / p99 | P p50 / p99 | server ms | optimizer µs | replans | CPU ms | wall s | peak RSS MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **P_first** | **22.6 / 38.3** | 8.2 / 39.3 | **644 ± 76** | **52,948** | **0** | **488.7** | **1.3** | 2,717.1 |
| R_first | 1.9 / 2.4 | 31.9 / 39.4 | 362 ± 8 | 362,152 | 3 | 294.8 | 1.0 | 2,717.2 |
| alternating | 2.0 / 2.2 | 36.4 / 37.2 | 411 ± 2 | 409,992 | 11 | 317.2 | 1.1 | 2,717.2 |
| shuffled | 1.8 / 2.2 | 34.3 / 42.2 | 395 ± 1 | 394,680 | 8 | 309.0 | 1.1 | 2,717.2 |

- R examines 480,000 documents in P_first against 24 in R_first: 20,000×, the wrong-plan ratio exactly.
- **Control.** The same queries with `.skip()` removed: per-query p50 1.1–1.4 ms in every order, and CPU
  44.8–53.4 ms per run. Order no longer matters.
- **Sweep.** Changing the skip in P_first moves the bar, and R flips where the bar crosses R's wrong-plan cost.
  - R's p50 is 2.3 ms at skip 1,800 (bar 19,060) and 26.3 ms at skip 2,000 (bar 21,160).
  - This gives a third axis, besides order and class, along which the same code changes latency.

**Two signals point the "wrong" way:**
- **The P class is faster in the buggy order** (8.2 vs 31.9 ms p50). In the other orders P is replanned, so it pays
  for planning.
- **Planner time is lowest in the buggy order** (52,948 vs 362,152 µs). The cost has moved out of the planner and
  into execution.

A hotspot search keyed on planner time, or on the whole run's mean, would point at the healthy order. The signal is
per class: R's latency splits 22.6 vs 1.9 ms.

**What timers should show.**
- In P_first, each R query spends about its whole latency (~23 ms) inside `CachedPlanStage::pickBestPlan`, almost
  all of it under `child()->work()` at `cached_plan.cpp:97`: the caller's time roughly equals the callee's.
- The loop at :87 iterates about 20,000 times per R query and exits through the IS_EOF branch at :127.
- In the other orders, R takes about 2 ms, and P's time moves into `MultiPlanStage::runTrials`.

**Where to put counters and timers.** The same as bug 1, plus a counter on which exit the trial loop takes (enough
results at :122, end of plan at :127, or replan at :162). The exit, not the duration, is what differs between R in
P_first and R elsewhere.

## 3. SERVER-32452 (W5): an expensive query makes wrong plans permanent

**Ticket.** [SERVER-32452](https://jira.mongodb.org/browse/SERVER-32452), *"Replanning may not occur when a plan
with an extremely high 'works' value is cached"*, fixed in 4.1.1 (2018). The fix introduced inactive cache entries
and the ×2 growth rule; the defect is reachable again on 8.2.12 (W5). The same mechanism was filed again as
[SERVER-77901](https://jira.mongodb.org/browse/SERVER-77901) and closed Won't Fix in 2023 as "not a significant
performance issue in realistic scenarios".

**What goes wrong.** Three classes share one shape, `find({a:<int>, b:<int>})`, on 1,000,000 documents with indexes
`{a:1}` and `{b:1}`:

| class | query | results | right plan | wrong plan |
|---|---|---:|---|---|
| E | `{a: rare, b: 0}` | 20 | `{a:1}`, 20 documents | `{b:1}`, 780,000 documents |
| H | `{a: 0, b: rare}` | 20 | `{b:1}`, 20 documents | `{a:1}`, 780,000 documents |
| M | `{a: MA, b: MB}` | 5 | either, 200,000 documents | either |

M is a legitimately expensive instance, not a defect. If M's planning is the one that promotes the cache entry,
`works` becomes 200,001 and the replan bar 2,000,010, which is larger than the collection. From then on no plan can
exceed the bar, so a wrong plan for H runs to the end inside the trial loop every time.

**Measurements** (`experiments/cliffs/2026-09-15-w5-works-ratchet/`: `report.txt`, `resources.txt`, `w5.jsonl`;
collection `docs_bar`, 60 queries per run, `{M×2, E×9, H×9}` per epoch; only the position of the M queries
differs):

| order | H p50 / p99 | E p50 | M p50 | server ms | replans | CPU ms | wall s | peak RSS MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **M_first** | **384.3 / 392.0** | 1.9 | 103.7 | **11,338** | **0** | **10,892.7** | **11.6** | 2,382.8 |
| M_last | 2.6 / 3.7 | 2.2 | 287.4 | 1,747 | 53 | 1,716.0 | 2.4 | 2,382.5 |
| M_middle | 2.0 / 2.6 | 2.1 | 286.7 | 1,708 | 52 | 1,687.8 | 2.4 | 2,382.7 |

- Documents scanned: 22,260,540 in M_first against 1,201,080 (18.5×).
- The replan bar stays at 200,001 works for the 1,300 queries that follow (recorded in `w5.jsonl`).
- **M is faster in the buggy order** (103.7 vs about 287 ms p50). In the other orders M's plan can never stay
  cached: the entry's `works` goes 21 → 42 → 84 as M fails to promote it, so M plans again every time.
- **Control collection** `docs` (no M class). Order still changes server time (58 vs 5 ms per run) and replans (58
  vs 5). Per-query p50 is 2.1–2.2 ms alternating vs 1.4–1.5 ms blocked. Documents examined are identical (1,200),
  so only time shows the difference.
- The per-query percentiles come from one traced run per order (27 H queries each); CPU and wall come from separate
  runs without tracing.

**What timers should show.**
- In M_first, every H query spends about 384 ms in `CachedPlanStage::pickBestPlan`. Almost all of it is under
  `child()->work()` at `cached_plan.cpp:97`, as `IXSCAN{a}` + FETCH runs to the end. Healthy H takes about 2 ms.
- In M_last and M_middle, M's time is in `MultiPlanStage::runTrials`.

So the two failure modes put the time under different callees of the same caller: immunity (H stuck on a wrong
plan) and thrashing (M never cached). Within one run of M_first, queries of one shape and one code path split into
about 2 ms (E) and about 384 ms (H): a bimodal distribution at a single code block.

**Where to put counters and timers.** The same as bugs 1 and 2. Also record the bar (`maxWorksBeforeReplan`,
`cached_plan.cpp:75-76`) per query: it is the variable that latches.

## 4. Hash-join eligibility bound (W2)

**Ticket.** None filed; tracked as W2 (`bugs/systems/mongodb/hash-join/`). The bound is the setting
`internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000`.

**What goes wrong.** `$lookup` chooses its join algorithm by the size of the foreign collection.
- Up to 10,000 foreign documents, it builds a hash table once (`HASH_LOOKUP`).
- At 10,001 it falls back to a nested-loop join (`NESTED_LOOP`), which scans the foreign collection once per local
  document.

The bound guards memory, but the hash table at 10,001 documents is under a megabyte.

**Measurements** (`experiments/cliffs/2026-09-15-w2-hash-join/report.txt`;
`experiments/instruments/2026-09-15-w2-resource-cost/README.md`):

| foreign documents | join | documents examined | median ms |
|---:|---|---:|---:|
| 9,998 | HASH_LOOKUP | 11,998 | 16.15 |
| 9,999 | HASH_LOOKUP | 11,999 | 12.83 |
| 10,000 | HASH_LOOKUP | 12,000 | **11.41** |
| **10,001** | **NESTED_LOOP** | **20,004,000** | **2,479.86** |
| 10,002 | NESTED_LOOP | 20,006,000 | 2,481.53 |
| 10,010 | NESTED_LOOP | 20,022,000 | 2,473.55 |

- 217× latency and 1,667× documents for one more foreign document. The 2,000 local documents each scan
  10,001 foreign ones (2,000 × 10,001 + 2,000 = 20,004,000).
- CPU per query: 19.1 ms with the hash join, 2,758.4 ms with the nested loop (145×), 18.1 ms with the bound raised
  to 20,000.
- Peak memory was not reliably measured. The script read the cgroup's `memory.peak` after a reset that this
  kernel silently ignores, so the identical 208.0 MB in all three rows is a stale watermark, not a per-run peak.
  What shows that memory is not the issue is the hash table's size: under a megabyte at 10,001 documents,
  against a 100 MB spill threshold (`experiments/instruments/2026-09-15-w2-resource-cost/README.md`).

**Where the time goes.**
- Decision at planning time:
  - `query/planner_analysis.cpp:1094` `determineLookupStrategy` calls `isEligibleForHashJoin` at :1153, only when
    disk use is allowed.
  - `isEligibleForHashJoin` (:946) compares the document count at :950 and the data size at :952; the finder marks
    both **heuristic**.
- Cost at execution time, in the SBE engine:
  - nested loop: `exec/sbe/stages/loop_join.cpp:138` `LoopJoinStage::getNext` re-opens its inner side through
    `openInner` (:125) for every local document;
  - healthy: `exec/sbe/stages/hash_lookup.cpp:140` `HashLookupStage::open` builds the table once.

**What timers should show.** A timer on `getNext` with a counter on `openInner` gives 2,000 re-opens per query
above the bound, and roughly 2,480 ms in that subtree, which is the whole query. Below it the subtree is absent and
the time sits in `HashLookupStage`. Caller–callee correlation is within the execution tree (`getNext` against
`openInner`'s inner scan). Linking the cost back to the decision needs the plan's join type recorded with each
query, because the decision ran earlier, at planning time.

**Already visible without tracing.** `explain` shows the join strategy, and `serverStatus` counts nested-loop joins
(`query.lookup.nestedLoopJoin`, `stats/counters.h:422-423`). Use this bug to check that the method finds a known
step, not to show it finds something new.

## 5. SERVER-14034 (W1): explode-for-sort cap

**Ticket.** [SERVER-14034](https://jira.mongodb.org/browse/SERVER-14034), closed fixed 2014-06-04. It reported this
cliff when the cap was 50; the fix raised the cap to 200, and the same cliff is reached at 201.

**What goes wrong.** The query is `find({tag: {$in: [k values]}}).sort({ts: 1}).limit(20)` on a compound index
`{tag:1, ts:1}`, with 2,000,000 documents.
- With at most 200 values (`internalQueryMaxScansToExplode = 200`), the planner "explodes" the `$in` into one index
  scan per value and merges them in sort order (`SORT_MERGE`), so it reads about one key per value plus the limit.
- At 201 values it gives up and takes one index scan over every matching key, followed by a blocking sort.

**Measurements** (`experiments/cliffs/2026-09-15-w1-explode-for-sort/report.txt`, from `sweep-n2000000.jsonl`):

| `$in` values | plan | keys examined | median ms |
|---:|---|---:|---:|
| 50 | SORT_MERGE | 69 | 1.45 |
| 100 | SORT_MERGE | 119 | 2.09 |
| 190 | SORT_MERGE | 209 | 4.47 |
| 200 | SORT_MERGE | 219 | **4.61** |
| **201** | **IXSCAN + blocking SORT** | **1,005,001** | **359.51** |
| 210 | IXSCAN + blocking SORT | 1,050,001 | 375.76 |
| 250 | IXSCAN + blocking SORT | 1,250,001 | 446.61 |
| 300 | IXSCAN + blocking SORT | 1,500,001 | 535.18 |

- 78× latency and 4,589× keys for one more value; 20 documents returned either way.
- Latency grows slowly with the number of values on each side of the cap, and jumps at it.
- The 8.2.12 run recorded no CPU or peak memory. A second run on this project's own release build of master at
  6d990ba (mongod 9.1.0, `-O2 -DNDEBUG`, 1,000,000 documents) shows the same cliff
  (`experiments/cliffs/mongo-explode-for-sort/README.md`):
  - 1.17 → 431.06 ms;
  - server CPU over 5 queries 0.00 → 2.17 s;
  - peak memory 471.4 MB for the whole run.
- The README headline in the W1 directory (5,025,001 keys, about 2,050 ms, 436×) comes from a larger run that has
  no committed record. Use the `report.txt` numbers above.

**Where the time goes.**
- Decision at planning time: `query/planner_analysis.cpp:1234` `explodeForSort`. It compares the scan count with
  the cap at :1366 (finder: **heuristic**) and is called at :1537; when it declines, a sort node is added instead.
- Cost at execution time:
  - above the cap, `exec/classic/sort.cpp:33` `SortStage::doWork` pulls every key from
    `exec/classic/index_scan.cpp:130` `IndexScan::doWork` before returning the first result;
  - below it, the time is in `exec/classic/merge_sort.cpp:56` `MergeSortStage::doWork` over the per-value scans.

**What timers should show.** At 200 values, about 4.6 ms spread over `MergeSortStage` and its scans. At 201, about
360 ms, nearly all in `SortStage` and its child `IndexScan`, called about 1,000,000 times. The caller–callee pair to
correlate is `SortStage::doWork` against `IndexScan::doWork`.

**Already visible without tracing.** `explain` shows the plan and keys examined, and the slow-query log records
that a sort stage ran. An existing tool (BFA) already catches this one. Like bug 4, this checks that a known step
is found.

## 6. SERVER-14423 (W4): the 101-result trial period

**Ticket.** [SERVER-14423](https://jira.mongodb.org/browse/SERVER-14423), *"Plans which fetch different numbers of
documents can tie"*, filed 2014, open nine years, closed as a duplicate of
[SERVER-79400](https://jira.mongodb.org/browse/SERVER-79400) (fixed 2023). That fix added a tie-breaker on
documents examined, but the tie-breaker only fires when scores tie, and here they do not (2.0002 vs 1.0002).

**What goes wrong.** The multi-planner runs the candidate plans round-robin and stops as soon as one fills a batch of
`internalQueryPlanEvaluationMaxResults` (101) results, or finishes. A plan whose first 101 documents all match wins
outright, even when the whole scan is far longer.
- 3,000,000 documents, indexes `{a:1}` and `{b:1}`, query `find({a:1, b:5})`, laid out so that:
  - `{a:1}` reaches all 101 matches in its first 101 documents, then scans 2,950,000;
  - `{b:1}` reads 50,000 non-matching documents first, and 50,101 in total.
- The trial gives `a_1` a score of 2.0002 against 1.0002: a decisive wrong choice. The plan is then cached as
  active, and because it produces 101 results its cached trial always stops at "enough results"
  (`cached_plan.cpp:122`), so it is never replanned.

**Measurements** (`experiments/cliffs/2026-09-15-w4-trial-period/`: `report.txt`, `resources.txt`):

| case | plan | documents examined | median ms | CPU ms per query | peak RSS MB |
|---|---|---:|---:|---:|---:|
| **default, 101 results** | `a_1` | 2,950,000 | **1,418.7** | **1,524.8** | 2,182.9 |
| setting raised to 102 | `b_1` | 50,101 | **25.6** | 85.2 | 2,183.4 |
| plan `a_1` forced (hint) | `a_1` | 2,950,000 | 1,401.8 | 1,433.7 | 2,183.2 |
| plan `b_1` forced (hint) | `b_1` | 50,101 | 27.2 | 42.4 | 2,183.9 |

- 55× latency for a one-unit change of the setting.
- Raising the trial size 10× does not shrink the cliff. A data set with 1,000 matches falls off it at
  `maxResults` ≤ 1,000 with the same 57.8× in documents.
- Cache page requests per query: 3,744 vs 162.

**Where the time goes.**
- Decision at planning time: `exec/classic/multi_plan.cpp:504` `workAllPlans` stops the trial at :556 (finder:
  **heuristic** at column 56). The scores come from `query/plan_ranker_util.h:242`, whose candidate loop at :221 is
  marked **heuristic**.
- Cost at execution time, after planning has ended: `exec/classic/fetch.cpp:49` `FetchStage::doWork` over the
  `{a:1}` index scan, for 2,950,000 documents.

**Why medium, not strong.** Latency is steady from query to query (rsd 0.0005 at the default), so there is no
variance across requests to track. It changes only with the setting or the data layout. The decision is also cheap
(101 works per candidate) and finished before the cost starts, so a caller–callee correlation needs the chosen plan
recorded with each query. Timers will still show the hotspot clearly (`FetchStage` and its index scan, about
1,400 ms), but attributing it to the trial needs that extra step.
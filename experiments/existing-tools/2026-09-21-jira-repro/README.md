---
title: "N3 — Two Won't-Do plan-cache defects, reproduced on 8.2.12 by order permutation"
date: 2026-09-21
status: active
tags: [jira-repro, oracle-o3, pattern-b, plan-cache, metamorphic, measured, server-107471, server-79039]
---

# SERVER-107471 and SERVER-79039, reproduced

> **Both tickets were closed `Won't Do`.** *(Corrected 2026-10-02, N4: this file previously
> said "with zero comments and no reproduction attached" — wrong. SERVER-79039 has one comment,
> "the changes to the replanning behaviour are too risky"; SERVER-107471 has two, closing with
> "4.4 reached end of life… upgrade to v7.0+ and see if your issue reoccurs". Neither was closed
> for want of a repro.)*
> Both reproduce on this build, on default knobs, with the reported mechanism visible query by
> query. Neither needed a fix to be reverted or a knob to be moved; the only instrument is
> oracle O3 — submit one multiset of queries in two arrival orders.

Reproduce: `bugs/systems/mongodb/SERVER-107471/repro/run_s107471.sh`, `bugs/systems/mongodb/SERVER-79039/repro/run_s79039.sh`. MongoDB **8.2.12**,
`planRankerMode=multiPlanning` (the default), `internalQueryFrameworkControl=trySbeRestricted`,
**every plan-cache knob at its default** (`internalQueryCacheEvictionRatio=10`,
`WorksGrowthCoefficient=2`, `PlanEvaluationWorks=10000`, `CollFraction=0.3`,
`PlanEvaluationMaxResults=101`). Host facts in [`env.md`](env.md). Records in
[`s107471.jsonl`](s107471.jsonl) / [`s79039.jsonl`](s79039.jsonl), rendered in
[`s107471-report.txt`](s107471-report.txt) / [`s79039-report.txt`](s79039-report.txt), CPU and
memory in [`s107471-resources.txt`](s107471-resources.txt) /
[`s79039-resources.txt`](s79039-resources.txt).

Three independent repeats of every cell; tables show mean ± sd. Fresh namespaces `ch_s107471`
and `ch_s79039` — the w1/w4/w5 datasets in this dbpath were not touched.

---

## Why these two

`experiments/existing-tools/2026-09-21-retroactive-yield-o3/` claimed 13 of 56 MongoDB plan-cache defects would have
been caught by an order-permutation test, and every one of those 13 verdicts rested on the
ticket's own prose. These two are the load-bearing cases: MongoDB acknowledged both and closed
for the two reasons above — **not** for want of a reproduction, as this file first claimed. If they reproduce, the claim stops being a reading of
JIRA text and becomes two live, unfixed, vendor-acknowledged defects demonstrated by the oracle.

---

# Target 1 — SERVER-107471

*"Query Plan Cache Issue with Index Selection on High Disparity Index Values"*, reported
2025-07-14, **Closed / Won't Do**, 5 watchers, **0 comments**, no fixVersion. The reporter:

> *"regardless of whether skip is included or not, both queries generate the same `queryHash` and
> `planCacheKey`. However, the cached plan that incorporates a skip condition could lead to very
> inefficient query plans when the query value has a high disparity (e.g.
> `{"indexField10": NumberLong(93333)}`) without a skip condition, which retrieves only a single
> document."*

## 1. The premise holds

Checked first, because if `.skip()` had entered the key on 8.2.12 the ticket would simply be stale
and the honest answer would be to say so and stop.

| variant | `planCacheKey` | `queryHash` |
|---|---|---|
| `find(F, proj).limit(10)` | `8C39E5AA` | `D4D54D3E` |
| `find(F, proj).skip(5000).limit(10)` | `8C39E5AA` | `D4D54D3E` |
| `find(F', proj).limit(10)` | `8C39E5AA` | `D4D54D3E` |
| `find(F', proj).skip(5000).limit(10)` | `8C39E5AA` | `D4D54D3E` |

**Neither `skip` nor `limit` is encoded.** One cache entry for all four. Premise holds, and the
same probe ([`probe0_premise.js`](probe0_premise.js)) shows a `sort` or a `projection` *does* change the key — so
this is a specific property of `skip`/`limit`, not a general insensitivity.

## 2. The mechanism, which the ticket does not spell out

Read off the source (`~/src/mongo`, master @ `6d990ba`, 2026-09-10 — **not** the 8.2.12
tag; the measured behaviour below is what makes the citation load-bearing, the source only names
it):

```
trial_period_utils.cpp:37-48   numResults = min(planEvaluationMaxResults, limit)   <- NO skip term
cached_plan.cpp:75-76          maxWorksBeforeReplan = internalQueryCacheEvictionRatio * decisionWorks
cached_plan.cpp:87             for (i = 0; i < maxWorksBeforeReplan; ++i)          <- the whole trial
cached_plan.cpp:128-129        IS_EOF -> _bestPlanChosen = true                    <- no replan, ever
multi_plan.cpp:568-573         "First plan to hit EOF wins automatically."
plan_cache.h:675-760           getNewEntryState: ratchet at :733, active no-op at :717-722
```

So the trial-period result target is `min(101, limit)` and **contains no skip term at all**, while
the `SKIP` stage sits *under* the `LIMIT` in the plan: every skipped document costs a work unit and
yields no result. And a cached plan that reaches EOF inside `maxWorksBeforeReplan` iterations is
declared fine — the replan loop is literally bounded by `10 x decisionWorks`. Two consequences,
both measured below:

1. **The winning plan changes.** Trial productivity is `advances / works` measured at the root,
   *after* the skip, so a plan that is productive per-document but must be entered from the wrong
   end loses ground to one that streams — and `multi_plan.cpp:568` gives the whole trial to
   whichever plan reaches EOF first.
2. **`decisionWorks` grows by ~S** — and `decisionWorks × internalQueryCacheEvictionRatio` **is the
   replan bar** (`cached_plan.cpp:75-76`). `.skip(5000)` anywhere in the workload sets a ~50 000-read
   bar for *every* query of that shape, including queries that contain no skip at all.

Measured directly, same filter, same projection, same limit, only the skip differs:

| query | winning plan | trial works | first-cached `decisionWorks` |
|---|---|---:|---:|
| `find({indexField1:7, indexField10:0}, proj).limit(10)` | `IXSCAN{indexField10}` | 10 | 10 |
| `...skip(1000).limit(10)` | **`IXSCAN{indexField1}`** | 1 064 | 1 064 |
| `...skip(5000).limit(10)` | **`IXSCAN{indexField1}`** | 5 274 | 5 274 |

## 3. The construction

1 000 000 documents, indexes `{indexField1:1}` and `{indexField10:1}`.
`indexField1 = 7` on 20 000 documents; `indexField10 = 0` on 999 000; `indexField10 = 93333+k` on
**exactly one** document each, for 1 000 values of k. That is the ticket's literal, and the
"disparity" is **999 000×**.

| class | query | results | right plan | wrong plan |
|---|---|---:|---|---|
| **P** "paginated" | `find({indexField1:7, indexField10:0}, proj).skip(5000).limit(10)` | 10 | `IXSCAN{indexField1}` — 5 274 reads | — |
| **R** "rare" | `find({indexField1:7, indexField10:93333+k}, proj).limit(10)` | 1 | `IXSCAN{indexField10}` — 1 read | `IXSCAN{indexField1}` — **20 000 reads** |

Multiset per epoch: 4 P + 8 R, three epochs, 36 queries. Every order below is a permutation of it.

## 4. Result — O3 violated, 8.6× documents, 20 000× on one class

| order | docs examined | server ms | optimizer µs | replans | queries > 1 000 reads | final cache entry |
|---|---:|---:|---:|---:|---:|---|
| **P_first** | **543 288 ± 0** | 644 ± 76 | 52 948 ± 20 839 | **0** | **36 / 36** | `indexField1_1`/ACTIVE **w=5274** |
| R_first | 63 312 ± 0 | 362 ± 8 | 362 152 ± 8 047 | 3 | 12 / 36 | `indexField1_1`/inactive w=32 |
| alternating | 63 312 ± 0 | 411 ± 2 | 409 992 ± 1 576 | 11 | 12 / 36 | `indexField10_1`/ACTIVE w=2 |
| shuffled | 63 312 ± 0 | 395 ± 1 | 394 680 ± 1 776 | 8 | 12 / 36 | `indexField10_1`/ACTIVE w=2 |

The last column counts queries reading over 1 000 documents. The floor is **12** — the 12 P queries
legitimately read 5 274 each to page past a `skip(5000)`, and that is not a defect. `P_first`'s 36
means **all 24 R queries joined them**, each reading 20 000 documents to return one.

| O3 check | worst/best | verdict |
|---|---:|---|
| documents examined | **8.6×** | VIOLATED |
| server time | 1.8× | VIOLATED |
| optimizer CPU | 7.7× | VIOLATED |
| final cached plan | 2 distinct indexes across 4 orders | VIOLATED |

Per class, the aggregate understates it badly:

| order | P (paginated) | **R (rare, 1 document)** | plan R used |
|---|---:|---:|---|
| P_first | 63 288 | **480 000** | `IXSCAN{indexField1}` 24/24 |
| R_first | 63 288 | **24** | `IXSCAN{indexField10}` 24/24 |

**The R class moves by 20 000×** — exactly the wrong-plan ratio, i.e. every R query runs the
catastrophic plan to completion, 24 times out of 24, with **`replans = 0`**. The mechanism that
exists to catch this did not fire once, because P's `.skip(5000)` had set the bar to 52 740 reads
and the wrong plan only costs 20 001.

## 5. The control: delete the `.skip()`, change nothing else

| order | docs examined | server ms | replans | queries > 1 000 reads | final cache entry |
|---|---:|---:|---:|---:|---|
| P_first | 144 ± 0 | 0 | 0 | 0 / 36 | `indexField10_1`/ACTIVE w=10 |
| R_first | 144 ± 0 | 0 | 0 | 0 / 36 | `indexField10_1`/ACTIVE w=2 |
| alternating | 144 ± 0 | 0 | 0 | 0 / 36 | `indexField10_1`/ACTIVE w=2 |
| shuffled | 144 ± 0 | 0 | 0 | 0 / 36 | `indexField10_1`/ACTIVE w=2 |

Same data, same filters, same multiset, same orders, same repeats. **O3 holds on every counter**
and the cached plan is the same index in all four orders. The only residual is optimizer CPU
(347 ± 14 µs vs 182 ± 0.5 µs, 2.0× — but 165 µs in absolute terms, and the plan and the work are
identical).

> **`.skip(S)` is therefore the causal variable, not the parameter value.** This is the distinction
> the ticket itself does not draw, and it is what separates SERVER-107471 from W5: W5 needed a
> legitimately expensive *parameter instance* to poison the bar; here a pagination cursor does it,
> on a filter that is character-for-character the same.

## 6. How much tuning? — the sweep answers it with the mechanism's own formula

The one genuinely chosen number is `N_HOT = 20 000`, which fixes the wrong plan's cost at 20 001
reads. Given that, the mechanism *predicts* immunity exactly when
`10 × decisionWorks > 20 001`. Sweeping the skip, order `P_first`, everything else fixed:

| skip | `decisionWorks` | replan bar | R docs | plan R used | replans | predicted |
|---:|---:|---:|---:|---|---:|---|
| 0 | 10 | 100 | 24 | `indexField10` | 0 | correctable |
| 1 000 | 1 064 | 10 640 | 24 | `indexField10` | 3 | correctable |
| 1 500 | 1 590 | 15 900 | 24 | `indexField10` | 3 | correctable |
| **1 800** | **1 906** | **19 060** | 24 | `indexField10` | 3 | correctable |
| **2 000** | **2 116** | **21 160** | **480 000** | **`indexField1`** | **0** | **immune** |
| 5 000 | 5 274 | 52 740 | 480 000 | `indexField1` | 0 | immune |
| 10 000 | 10 537 | 105 370 | 480 000 | `indexField1` | 0 | immune |

The bar crosses 20 001 between skip 1 800 (bar 19 060) and skip 2 000 (bar 21 160), and the
behaviour flips in exactly that interval — which is not a fit, it is `cached_plan.cpp:87`'s loop
bound read out loud. **The parameter is derived, not tuned** — and the general
statement it licenses is knob-free:

> **Any `.skip(S)` makes every plan of that query shape costing under `10 × S` reads permanently
> immune to replanning, for every parameter instance of the shape, including instances with no
> skip.** A page-500 pagination cursor (`skip(5000)`) protects any wrong plan up to 50 000 reads.

Two details in that table are worth reading rather than skimming. `skip = 0` has **zero** replans
because without a skip the P class picks `IXSCAN{indexField10}` — the same plan R wants — so
nothing ever needs correcting. The rows in between (skip 100–1 800) have **three** replans: P does
pick the wrong-for-R plan, the bar is low enough that R trips it, and the machinery works. Those
rows are SERVER-79039's thrash, and the rows below are SERVER-107471's immunity. **The same knob,
crossed in the same direction, moves the system from one ticket to the other** — which is the
cleanest evidence available that they are one defect with two signs.

---

# Target 2 — SERVER-79039

*"Plan cache entries can be evicted and replanned continuously for certain workload patterns"*,
reported 2023-07-17, **Closed / Won't Do**, 10 watchers, **0 comments**, no fixVersion:

> *"we can run into a cycle of cache->evict->replan->cache for the same query shape and same plan
> depending on the parameters … when the higher work plan triggers the eviction, the cache entry
> remains in an 'inactive' state. If the next query to activate it has a lower works value, then
> we'll use the new one. This puts us in a state where its like the higher work query never
> happened, and its possible to evict and replan again."*

This is the **opposite pole of W5**: W5 latched the bar too high and never replanned; 79039
oscillates and replans forever. Same `getNewEntryState`/`deactivate` machinery, and permuting the
arrival order of one multiset moves the system between the two.

## 1. The construction — deliberately *not* a mis-planning bug

1 000 000 documents, indexes `{a:1}` and `{b:1}`, one shape `find({a:<int>, b:0})`:

| class | query | results | plan | works |
|---|---|---:|---|---:|
| **C** cheap | `find({a: 1..1000, b: 0})` | 5 | `IXSCAN{a}`, EOF | **6** |
| **E** expensive | `find({a: 900001, b: 0})` | 3 | `IXSCAN{a}`, EOF | **50 001** |

**Both classes want the same plan, and both get it, in every order.** Nothing is mis-estimated and
nothing is mis-planned. The only thing that differs is how much work that one plan costs — which
is precisely the quantity the plan cache stores and updates non-commutatively. Same
`planCacheKey = 51C56FDD`, verified. Multiset per epoch: 6 C + 6 E, four epochs, 48 queries.

## 2. The cycle, visible in eight queries

The `works` field of the single cache entry, read after every query (`alternating`):

```
q1  C  ->  a_1 / inactive  w=6        q5  C  ->  a_1 / ACTIVE    w=6
q2  E  ->  a_1 / inactive  w=12       q6  E  ->  a_1 / inactive  w=12
q3  C  ->  a_1 / ACTIVE    w=6        q7  C  ->  a_1 / ACTIVE    w=6
q4  E  ->  a_1 / inactive  w=12       q8  E  ->  a_1 / inactive  w=12   ...
```

`[6, 12, 6, 12, 6, 12, 6, 12, …]` for all 48 queries. The bar is **lowered 23 times** and **never
once reaches E's real cost of 50 001**. That is the reporter's sentence, measured: *it is like the
higher work query never happened.*

The three transitions that produce it, from `plan_cache.h:675-760`:

| query | old entry | branch taken | new entry |
|---|---|---|---|
| E | inactive, w=6 | `newWorksGreater` -> ratchet `max(w+1, w x 2.0)` (`:733`) | inactive, **w=12** |
| C | inactive, w=12 | `!newWorksGreater` -> promote (`:750-757`) | **ACTIVE, w=6** |
| E | ACTIVE, w=6 | cached plan exceeds `10 x 6` works (`cached_plan.cpp:87`) -> **replan** | inactive, w=12 |

The ratchet multiplies, the promotion *assigns*, and the loop bound reads whichever value happens
to be there. `max`, `x2` and *assign* do not commute — which is why permuting the arrival order
changes the outcome, and why 79039 and W5 are the same rule failing in opposite directions.

## 3. Result — O3 violated 12.3× in optimizer CPU, while **every work counter says 1.0×**

| order | docs examined | server ms | optimizer µs | planning works | replans | wasteful replans |
|---|---:|---:|---:|---:|---:|---:|
| **alternating** | 1 200 120 ± 0 | 1 715 ± 18 | **1 722 968 ± 16 668** | **3 600 504 ± 0** | **23** | **23** |
| blocked_CE | 1 200 120 ± 0 | 1 634 ± 49 | 1 641 589 ± 46 797 | 3 600 162 ± 0 | 4 | 4 |
| **blocked_EC** | 1 200 120 ± 0 | **766 ± 43** | **139 714 ± 5 978** | **300 006 ± 0** | **0** | **0** |
| shuffled | 1 200 120 ± 0 | 1 617 ± 30 | 1 623 640 ± 27 880 | 3 600 306 ± 0 | 11 | 11 |

| O3 check | worst/best | verdict |
|---|---:|---|
| documents examined (profiler) | **1.0×** | HOLDS |
| `queryExecutor.scannedObjects` (server-wide) | **1.0×** | HOLDS |
| server time | 2.2× | VIOLATED |
| `multiPlanner.classicMicros` | **12.3×** | VIOLATED |
| multi-planning invocations | **24.0×** (48 vs 2) | VIOLATED |
| `multiPlanner.classicWorks` | 12.0× | VIOLATED |
| replans (+1) | 24.0× | VIOLATED |

`blocked_EC` reaches a true steady state — **2 multi-plannings for 48 queries, 0 replans, `works`
fixed at 50 001 for every one of the 48 observations.** `alternating` never settles. Same multiset.

**All of the replans are wasteful.** `planCache.classic.replanned_plan_is_cached_plan` (the counter
SERVER-98987 added in **8.2.0**) equals `replanned` in every order: **100 % of replans re-derive
the plan that was already cached.** That is the ticket's "same query shape and same plan",
confirmed by MongoDB's own instrumentation, in the release that added it.

**It is a steady state, not a transient** (O3 condition (c)):

| order | epoch 0 | epoch 1 | epoch 2 | epoch 3 |
|---|---|---|---|---|
| alternating | 5 rp / 12 mp | 6 rp / 12 mp | 6 rp / 12 mp | 6 rp / 12 mp |
| blocked_CE | 1 rp / 8 mp | 1 rp / 7 mp | 1 rp / 7 mp | 1 rp / 7 mp |
| blocked_EC | 0 rp / 2 mp | **0 rp / 0 mp** | **0 rp / 0 mp** | **0 rp / 0 mp** |

## 4. How much tuning? — the boundary is exact to one document

Prediction: E thrashes exactly when its works exceeds the bar the cheap class sets, i.e.
`N_E + 1 > 10 × 6 = 60` — the same `cached_plan.cpp:87` loop bound, from the other side. Sweeping
the number of documents at the expensive value, order `alternating`, everything else fixed (three
epochs here rather than four, hence 17 replans at saturation rather than 23):

| N_E | E works | bar | replans | outcome | predicted |
|---:|---:|---:|---:|---|---|
| 40 | 41 | 60 | 0 | stable | stable ✓ |
| 55 | 56 | 60 | 0 | stable | stable ✓ |
| **59** | **60** | **60** | **0** | **stable** | stable ✓ |
| **60** | **61** | **60** | **17** | **thrash** | thrash ✓ |
| 70 | 71 | 60 | 17 | thrash | thrash ✓ |
| 500 … 50 000 | 501 … 50 001 | 60 | 17 | thrash | thrash ✓ |

**The boundary lands on the exact document the formula names** — `N_E = 59` stable, `N_E = 60`
thrashing — and the default `N_E = 50 000` is 833× past it, so the headline is not sitting on a
knife edge. The workload was not tuned until it broke; the breaking point was computed and then
confirmed.

---

## What 8.2.12 actually exposes (the brief asked; here is the inventory)

`db.serverStatus().metrics.query` on this build, for the counters that bear on either ticket:

| counter | what it sees here |
|---|---|
| `planCache.classic.replanned` | 23 / 4 / 0 / 11 across the four 79039 orders. **Under-reports**: see correction 2 below. |
| `planCache.classic.replanned_plan_is_cached_plan` | SERVER-98987, Fixed in **8.2.0**. Equals `replanned` in every order — 100 % waste. |
| `planCache.classic.cached_plans_evicted` | **0 in every order of both experiments.** The cycle is replan-and-rewrite, not eviction — despite SERVER-79039's title saying "evicted". An operator watching this counter sees nothing at all. |
| `planCache.classic.inactive_cached_plans_replaced` | **0 in every 79039 order** (the entry is rewritten with the *same* plan, so nothing is "replaced") but 2-12 per 107471 order (where the plan really does alternate). A second, independent confirmation of the ticket's "same plan". |
| `planCache.classic.{hits,misses,skipped}` | 79039 alternating: 23 hits / 26 misses vs blocked_EC's 46 / 3. `skipped` is 0 throughout — every query really did reach the cache. |
| `planCache.{totalQueryShapes,totalSizeEstimateBytes}` | SERVER-105489-era size accounting. One shape, ~4.8 kB. Says nothing about thrash. |
| **`multiPlanner.classicCount` / `classicMicros` / `classicWorks`** | **The instrument that works.** 48 vs 2 invocations, 12.3x CPU, 12.0x works, on an identical multiset. |
| `multiPlanner.stoppingCondition.{hitEof,hitResultsLimit,hitWorksLimit}` | present; confirms these trials end on EOF, not on the works limit. |
| `queryExecutor.{scanned,scannedObjects}` | **Blind.** Identical to the digit across all four 79039 orders. |

## Resources — CPU and peak memory

mongod runs in a systemd user cgroup (`tools/harness/start_mongod_cgroup.sh`,
`/sys/fs/cgroup/.../mongod-ch.service`), so CPU and memory exclude the mongosh client. Quiet mode
(no profiler, no per-query `$planCacheStats` polling), 3 repeats, mean ± sd.

**`memory.peak` is not usable on this kernel (6.18.51): the reset write is accepted and silently
ignored, so it returns a stale global watermark.** Both harnesses sample `memory.current` at 10 ms
instead.

| target | arm | order | CPU ms | docs scanned | optimizer µs | peak RSS MB |
|---|---|---|---:|---:|---:|---:|
| 107471 | skip5000 | **P_first** | **488.7 ± 39.2** | 543 288 | 51 168 ± 10 312 | 2 717.1 ± 0.1 |
| 107471 | skip5000 | R_first | 294.8 ± 9.1 | 63 312 | 248 905 ± 9 060 | 2 717.2 ± 0.1 |
| 107471 | noskip | P_first | 53.4 ± 11.5 | 144 | 347 ± 14 | 2 717.3 ± 0.1 |
| 107471 | noskip | R_first | 45.9 ± 3.2 | 144 | 182 ± 0.5 | 2 717.5 ± 0.2 |
| 79039 | — | **alternating** | **1 767.2 ± 9.4** | 1 200 120 | 1 604 078 ± 9 350 | 3 447.5 ± 35.1 |
| 79039 | — | blocked_CE | 1 778.8 ± 11.3 | 1 200 120 | 1 616 090 ± 1 972 | 3 422.4 ± 0.8 |
| 79039 | — | **blocked_EC** | **819.0 ± 28.1** | 1 200 120 | 145 441 ± 5 889 | 3 420.7 ± 1.0 |
| 79039 | — | shuffled | 1 769.5 ± 4.7 | 1 200 120 | 1 606 799 ± 3 518 | 3 419.4 ± 0.1 |

- **Order costs 1.66× the CPU** on 107471 (skip arm) and **2.17×** on 79039, for identical
  multisets. The no-skip control is 1.19× — at 45–53 ms, that is the floor.
- **Peak RSS is flat.** 107471: 2 716.8–2 718.0 MB across all 24 runs, within-order sd ≤ 0.3 MB.
  79039: within-order sd ≤ 1.0 MB for three of four orders. The one 3 497 MB sample is repeat 0 of
  the first order measured after the build — WiredTiger cache fill, not an order effect;
  `memory.current` is monotone under WT warm-up, which is a limitation of sampling it, and it is
  reported rather than dropped. Order changes *which plan runs and how often planning runs*, not
  what is allocated. The measurement floor is the pinned 8 GB WT cache, so anything under a few MB
  is invisible; the same sampler resolved the 2.17× CPU difference on the same runs.

## Scoping — the cost-based ranker (`automaticCE`, the 8.3 default)

| target | docs examined | keys examined | replans | plan cache entry | server ms |
|---|---|---|---|---|---|
| 107471 | 60 144 in **all four** orders | 3.23–3.28 M | 0 in all four | **none created** | 1 004–1 146 |
| 79039 | 192 in **all four** orders | 24.5–27.8 M | 0 in all four | **none created** | 5 468–6 108 |
| 79039, `multiPlanning` reference | 1 200 120 | 1 200 120 | 23 / 0 | one entry | 790–1 677 |

**Both defects are order-insensitive under CBR, and for the same structural reason as W5: CBR
creates no plan cache entry for these shapes, so there is no hysteretic state to get wrong.** The
`docs examined` column is byte-identical across orders in both targets — the thing `multiPlanning`
could not manage.

But CBR is **not** uniformly better here, and the honest version of the scoping note has to say so.
It picks index intersection (`IXSCAN{a}, IXSCAN{b}` AND_SORTED) for both shapes. On 79039 that
examines **6 251× fewer documents and 20–23× more index keys**, and costs **5.5–6.1 s of server
time against 0.79–1.68 s** under `multiPlanning` — **3.3–7.7× slower**. Same documents-for-keys
trade W4, W5 and W8 found. So "the 8.3 default fixes it" is true about the *order dependence* and
false about the *cost*, and the right statement is that CBR removes this bug class by removing the
state, at a price on these shapes that has to be paid separately.

(The keys column varies a little *within* a target. That is not an order effect: both harnesses
follow W5 in never reusing a parameter value inside a run, so different orders draw different
rare/cheap values, and AND_SORTED's cost depends on where those documents sit in recordId order.
Under `multiPlanning` this is invisible — every counter is identical to the digit across orders —
so it only shows up once CBR makes the plan recordId-sensitive. Reported rather than smoothed.)

---

## Threats — including exactly how much tuning there was

Stated plainly, because "we tuned the workload until it broke" is the weakest form of this claim.

1. **One construction was tried and rejected for Target 1, and it is archived.**
   [`probe1_rejected_construction.js`](probe1_rejected_construction.js) is a `find({cat}).sort({ts:-1})` pagination shape with
   indexes on the filter field and the sort field. On that shape `.skip()` **did not** change the
   winning plan at any skip depth tried (1 000, 10 000) — the plan flipped with the *parameter
   value*, not the skip. Had only that construction been tried, the honest report would have been
   "premise holds, defect does not reproduce, the reporter mis-attributed a parameter-value effect
   to skip". The second construction — two equality predicates, two single-field indexes, which is
   the shape the ticket's own field names (`indexField1`, `indexField10`) describe — reproduces it.
   **So: 2 constructions, 1 worked. Target 2 needed 1 construction and worked first time.**
2. **The chosen constants, and what fixes them.** Target 1: `N_HOT = 20 000` (the wrong plan's
   cost) and `skip = 5 000`. Only their *ratio* matters, the mechanism names the threshold
   (`10 × decisionWorks > wrong-plan reads`), and the sweep locates it between skip 1 800 and
   2 000 — one sweep step. Target 2: `N_E = 50 000`, threshold `N_E ≥ 60`, located to the exact
   document. Neither headline sits near its boundary.
3. **Server knobs were not touched.** All plan-cache parameters were read off the running server
   and are at their shipped defaults; `planRankerMode` was restored to `multiPlanning` after the
   scoping run. `enableTestCommands=1` was already set on this mongod for unrelated reasons and no
   failpoint was used.
4. **Result-set sizes are all below 101 on purpose.** W4 showed a cached plan that produces 101
   results ends its trial with `_bestPlanChosen = true` and can never replan. Keeping result sets
   at 1, 3, 5 and 10 is what lets the replan machinery engage at all — otherwise these experiments
   would silently re-run W4. This is a real constraint on reachability and should be read as one:
   **both defects require query shapes whose result sets are small**, which is the pagination /
   point-lookup regime, not the bulk-scan regime.
5. **Target 2's expensive class needs a "needle after a long scan" distribution** — 3 matching
   documents inside a 50 000-key index range. That is a real pattern (`{tenant: bigTenant,
   status: rareStatus}`) but it is not universal, and the ticket's own phrasing ("for certain
   workload patterns … depending on the parameters") concedes the same scope.
6. **Neither reproduction is the reporter's workload.** These are minimal constructions that
   exhibit the reported mechanism on the reported version family. They do not prove the reporters'
   own systems failed this way.
7. **Single-node, cold-ish WiredTiger, no concurrent load, static data.** Notably: Percona's public
   diagnosis of the replanning loop is data churn (*"the re-planning loop occurs when data changes
   faster than the planner can adapt"*). **No document was written during any measured order** and
   the loop is still there, 23 times in 48 queries. Static data plus a mixed parameter distribution
   is sufficient; churn is not necessary. Same correction W5 made, now on the vendor's own ticket.
8. **The profiler, not `explain()`.** `explain()` re-runs the multi-planner and hides the
   cached-plan path entirely. Both harnesses read `system.profile` (recreated at 64 MB so the
   capped collection cannot roll the early transitions away). Cost numbers come only from quiet
   runs with the profiler and the state-polling off.

## Two corrections to existing project claims

1. **W5's "no work counter MongoDB exposes contains it" is too strong.** On 79039 the per-operation
   `docsExamined` (1 200 120) and the server-wide `queryExecutor.scannedObjects` (1 200 264) are
   **identical to the digit** across all four orders — exactly as W5 reported. But
   `metrics.query.multiPlanner.classicWorks` is **3 600 504 vs 300 006 (12.0×)** and
   `classicMicros` is **12.3×**. The discarded work *is* exposed on 8.2.12, in a server-wide
   aggregate under `multiPlanner`, just not in any per-operation counter. W5's README should be
   amended: the correct statement is "no *per-operation* work counter contains it".
2. **The wasteful-replan counter is necessary but not sufficient for diagnosis.** `blocked_CE` logs
   **4** replans against `alternating`'s **23** — a 5.75× apparent improvement — while costing
   **1.05×** the optimizer CPU (1 641 589 µs vs 1 722 968 µs). The difference is that `blocked_CE`'s
   expensive queries meet an *inactive* entry and go through full multi-planning, which is not
   counted as a replan at all. An operator watching only
   `planCache.classic.replanned{,_plan_is_cached_plan}` would score `blocked_CE` as nearly healthy.
   The counter that separates them is `multiPlanner.classicCount` (29 vs 48 vs **2**). This bears
   directly on SERVER-79039's own closing comment — *"in terms of diagnosability we could consider
   adding the original plan when a replanning happens"* — and says the diagnosability fix they
   contemplated would have missed half the cases.

## Verdict

| | premise on 8.2.12 | reproduces | O3 relation | headline |
|---|---|---|---|---|
| **SERVER-107471** | **holds** — `skip`/`limit` absent from `planCacheKey` | **yes** | **violated**, 4 orders of one multiset | 8.6× documents overall, **20 000× on the high-disparity class**, 0 replans; and the no-skip control is order-insensitive, so `.skip()` is causal |
| **SERVER-79039** | **holds** — one entry for both parameter classes | **yes** | **violated**, 4 orders of one multiset | **48 multi-plannings vs 2**, 23 replans vs 0, 12.3× optimizer CPU, **100 % of replans re-derive the cached plan** — with every per-operation work counter identical |

Both are **Pattern B′** (`docs/studies/main/patterns.md`): a decision taken on evidence
that did not generalise, then frozen. 107471 freezes it (a pagination cursor's `decisionWorks`
becomes a bar nothing can trip); 79039 refuses to freeze it (the bar is reset by the cheapest
instance, so the expensive one is re-learned and re-forgotten forever). They are the two failure
modes of one non-commutative update rule, and O3 exhibits both by permuting a list.

For the project's argument: these are **not** discoveries. Both were reported by users, both were
understood well enough by MongoDB to be triaged, and both were closed without a reproduction. What
was missing was a *test* — and the test is one line of specification (*same multiset, different
order, same cost*) plus a workload. That is the deliverable the maintainers asked for on
SERVER-32452 (*"I'm disinclined to mess with our plan selection logic unless we have empirical
evidence"*), and it is what `bugs/systems/mongodb/SERVER-107471/repro/run_s107471.sh` and `bugs/systems/mongodb/SERVER-79039/repro/run_s79039.sh` are.

---
title: "W4 — the 101-document trial period: a decision taken on a prefix that inverts the truth"
date: 2026-09-15
status: active
tags: [w4, oracle-o2, pattern-b, multiplanner, plan-cache, measured]
---

# W4 — the 101-document trial period

> **Oracle O2 (evidence sufficiency).** A planning decision must not be taken on evidence
> that could not distinguish the candidates. W4 is the sharper case: evidence that *did*
> distinguish them, **decisively and backwards**.

Reproduce: `bugs/systems/mongodb/trial-period/repro/run_w4.sh`. Server: MongoDB 8.2.12, `planRankerMode=multiPlanning`
(the default), `internalQueryFrameworkControl=trySbeRestricted`. Full host facts in
[`env.md`](env.md); per-candidate records in [`w4.jsonl`](w4.jsonl); rendered in
[`report.txt`](report.txt); resources in [`resources.txt`](resources.txt).

## The construction

3 000 000 documents, two **separate** single-field indexes `{a:1}` and `{b:1}` (a compound
`{a:1,b:1}` would answer the query outright and there would be no decision to make), and
one query: `find({a:1, b:5})`. Documents are laid out by recordId so that each plan's
*prefix* says the opposite of its *total cost*:

| recordId range | document | effect |
|---|---|---|
| `[0, 50 000)` | `{a:2, b:5}` | matches `b`, not `a` — poison for the `{b:1}` prefix |
| `[50 000, 50 101)` | `{a:1, b:5}` | **the only 101 matches** |
| `[50 101, 3 000 000)` | `{a:1, b:7}` | matches `a`, not `b` — the bulk of the `{a:1}` scan |

An index on `{a:1}` is ordered `(a, recordId)`, so scanning `a=1` starts at recordId 50 000
and its **first 101 documents are all matches** — productivity 101/101 = 1.0. Scanning
`b=5` starts at recordId 0, where the first 50 000 documents are all non-matches —
productivity 0/101 = 0.0. Run to completion the ordering reverses: `{b:1}` examines 50 101
documents, `{a:1}` examines 2 950 000.

## Why it happens — read out of the source, then confirmed to the digit

Two files decide this. `MultiPlanStage::workAllPlans`
([`multi_plan.cpp:504-596`](https://github.com/mongodb/mongo/blob/master/src/mongo/db/exec/classic/multi_plan.cpp))
works every candidate **round-robin, one `work()` per round**, and ends the trial *for every
candidate* as soon as **any one** of them either fills a batch or hits EOF. The score is
then ([`plan_ranker.h:53-107`](https://github.com/mongodb/mongo/blob/master/src/mongo/db/query/plan_ranker.h)
plus [`plan_ranker_util.h:201-247`](https://github.com/mongodb/mongo/blob/master/src/mongo/db/query/plan_ranker_util.h)):

```
score = 1 + advanced/works + eps*(noFetch + noSort + noIxisect) + (1 if isEOF)     eps = 1e-4
```

Two consequences, and they are the whole finding:

1. **Round-robin makes `works` essentially equal across candidates.** So `advanced/works`
   does not compare total cost — it compares *results produced in the first W works*. It is
   a **prefix race**.
2. **The EOF bonus is the only term that carries information about a plan's total cost** —
   "this plan finished, so its whole scan was cheap". And it is `+1`, which dominates
   everything else by design.

So the trial's two stopping conditions **race**, and which one fires decides the plan:

| condition that fires first | outcome |
|---|---|
| **full batch** (`internalQueryPlanEvaluationMaxResults` results) | the front-loaded plan wins on productivity 1.0; the EOF bonus never fires |
| **EOF** (a plan exhausts its index range) | that plan takes the `+1` and wins — correctly |

W4 simply makes the *wrong* condition win, by giving the expensive plan exactly enough
front-loaded matches to fill the batch. The EOF bonus — the one signal that would have
identified the cheap plan — never gets the chance to fire.

The score predictions were computed from the formula **before the run** and the server's own
per-candidate `score` field (exposed in `allPlansExecution`) came back identical:

| candidate | works | advanced | predicted | **server** |
|---|---:|---:|---:|---:|
| `a_1` (front-loaded, expensive) | 101 | 101 | 2.0002 | **2.0002** |
| `b_1` (cheap) | 101 | 0 | 1.0002 | **1.0002** |
| `a_1+b_1` (AND_SORTED) | 101 | 0 | 1.0001 | **1.0001** |

The winner is chosen by a **full 1.0 margin** — the most decisive verdict this ranker can
return — and it is the wrong plan. This is not a near-miss or a tie.

## The four conditions

### (a) Cost steps across the threshold — yes

| `maxResults` | winner | docs examined | median latency |
|---:|---|---:|---:|
| 50 | `a_1` | 2 950 000 | 1418.7 ms |
| **101** (default) | `a_1` | **2 950 000** | **1418.7 ms** |
| **102** | `b_1` | **50 101** | **25.6 ms** |
| 1 000 | `b_1` | 50 101 | 25.8 ms |
| 100 000 | `b_1` | 50 101 | 25.5 ms |

A **one-unit** change in the knob, 101 → 102, moves documents examined by **58.9×** and
latency by **55×**. The plan flips, exactly as asked.

### (b) Crossover violation — the abandoned plan was far cheaper at that point

Measured directly with `hint()`, i.e. the counterfactual plan at the same workload point:

| plan | keys | docs | median |
|---|---:|---:|---:|
| `hint({a:1})` — **what the trial picks** | 2 950 000 | 2 950 000 | 1401.8 ms |
| `hint({b:1})` — what it discarded | 50 101 | 50 101 | 27.2 ms |
| `AND_SORTED` — **the actual optimum** (see CBR, below) | 50 203 | **101** | **14.1 ms** |

The discarded single-index plan was **58.9× cheaper**. Against the best plan available at
all, the chosen plan examines **29 208×** the documents.

### (c) Invariance — raising the constant does not shrink the cliff

The point of the `docs_k1000` dataset: 1 000 matching documents instead of 101, so it trips
a knob raised **10×**.

| dataset | matching docs | trips at `maxResults` | cliff (docs) | cliff (latency) |
|---|---:|---:|---:|---:|
| `docs` | 101 | ≤ 101 | **58.9×** | 52.1× |
| `docs_k1000` | 1 000 | ≤ 1 000 | **57.8×** | 45.7× |
| `docs_mirror` | 101 | ≤ 101 | **58.9×** | 54.8× |

**Raising the constant 10× changed the cliff by 0.98× — it did not shrink.** The knob does
not set the *depth* of the cliff; it sets *how many matching documents a workload needs in
order to fall off it*. The rule is closed-form:

> a workload falls off this cliff whenever
> **(matching documents) ≤ `internalQueryPlanEvaluationMaxResults`** and the matches sit
> early in the expensive plan's index order.

Match count is a property of the **data**; the knob is a server constant. No setting of the
constant excludes the bad regime — so by condition (c) the defect is **structural**, not a
tuning error. This is the same verdict as W1, reached by an independent route.

### (d) Regime identification — what the heuristic should have conditioned on

`internalQueryPlanEvaluationMaxResults` conditions on **a result count**. The crossover is
governed by **where the matching documents sit in each candidate's index order** — a
property of the data that the trial period samples but the stopping rule never reads. The
`docs_mirror` dataset holds everything fixed and swaps only which index is front-loaded;
the winner swaps with it. So the governing variable is prefix position, not index identity,
not collection size, and not the result count the knob names.

## Resources — CPU and peak memory, per the standing requirement

From [`resources.txt`](resources.txt) (`bugs/systems/mongodb/trial-period/repro/w4_resource_cost.py`; mongod in a systemd
user cgroup, so the `mongosh` client's cost is excluded):

| phase | CPU ms/query | cache pages/query | peak RSS |
|---|---:|---:|---:|
| `hint({b:1})` — optimal plan, forced | 42.4 | 66 | 2183.9 MB |
| `hint({a:1})` — **the plan the trial picks** | **1433.7** | **3 731** | 2183.2 MB |
| unhinted, `maxResults=101` (default) | 1524.8 | 3 744 | 2182.9 MB |
| unhinted, `maxResults=102` | 85.2 | 162 | 2183.4 MB |

- **33.8× the CPU** and **56.5× the cache page requests, to save 0 MB.** Both candidates are
  streaming `IXSCAN`+`FETCH` with no blocking stage, so there is no per-query structure that
  could grow — the wrong decision buys nothing in memory. Peak RSS differs by **−0.6 MB**,
  i.e. the expensive plan measured marginally *lower*, which is the right way to read "flat".
  Unlike W2, this guard never claimed to be protecting memory, so a flat memory column is the
  expected result here, and it is reported as a measurement rather than assumed.
- The 56.5× cache-page ratio tracks the 58.9× document ratio, which is what establishes that
  the instrument can in fact resolve the difference it reports as absent in the RSS column.
- **The naive fix is not free:** at `maxResults=102` the query costs 85.2 ms CPU against
  42.4 ms for the forced optimal plan — **2.0×**, because the longer trial now works all
  three candidates ~50 000 times each. Extending the trial to obtain discriminating evidence
  costs roughly the query itself again. Any fix that just lengthens the trial pays this.

Caveats, stated rather than assumed away: peak RSS is dominated by the pinned 8 GB
WiredTiger cache, so per-query structures below a few MB are under the measurement floor.
Disk→cache traffic was ~0 because the collection is cache-resident, which makes every ratio
above a **lower bound** — a cache-resident scan is the cheapest this bad plan can be.

**Instrumentation note.** On this kernel (6.18) a write to cgroup `memory.peak` is *accepted
and silently ignored*, so `memory.peak` reads as a stale global watermark. An earlier version
of the harness reported it and produced four identical numbers, which would have been
mistaken for "memory is flat". Peak is now **sampled** from `memory.current`. Verified before
being relied on; `bugs/systems/mongodb/hash-join/repro/w2_resource_cost.py` has the same latent issue.

## The decision is then frozen

Pattern B's second half. At `maxResults=101` the plan cache entry is written and **active**:

```json
[{"plan": "ixscan:a_1", "isActive": true, "works": 101}]
```

MongoDB has two guards here, and this case slips between both
([`plan_cache_util.cpp:355-400`](https://github.com/mongodb/mongo/blob/master/src/mongo/db/exec/plan_cache_util.cpp)):

1. **don't cache ties** (SERVER-13675) — `tieForBest()` compares the *final* scores with
   epsilon `1e-10`. Our winner leads by 1.0. Does not fire.
2. **don't cache if the winner produced zero results** (SERVER-14071) — our winner produced
   101. Does not fire.

Both existing guards test for *non-discriminating* evidence. W4's evidence is
**decisively misleading**, which neither guard models. That is the precise gap, and it is
the argument for generalising the SERVER-13675 policy rather than adding a third special case.

## What actually fixes it: the cost-based ranker

[`cbr.txt`](cbr.txt) / [`cbr.jsonl`](cbr.jsonl), via `bugs/systems/mongodb/trial-period/repro/w4_cbr_probe.js`. On 8.2.12 the valid
`planRankerMode` values are `multiPlanning` (default) and `automaticCE`:

| ranker | dataset | winner | keys | docs | median |
|---|---|---|---:|---:|---:|
| `multiPlanning` | `docs` | `a_1` | 2 950 000 | 2 950 000 | 1498.8 ms |
| `multiPlanning` | `docs_k1000` | `a_1` | 2 950 000 | 2 950 000 | 1504.6 ms |
| `multiPlanning` | `docs_mirror` | `b_1` | 2 950 000 | 2 950 000 | 1503.2 ms |
| **`automaticCE`** | `docs` | **`a_1+b_1`** | 50 203 | **101** | **14.1 ms** |
| **`automaticCE`** | `docs_k1000` | **`a_1+b_1`** | 52 001 | **1 000** | **28.6 ms** |
| **`automaticCE`** | `docs_mirror` | **`a_1+b_1`** | 50 202 | **101** | **28.2 ms** |

**CBR picks the optimal plan on all three datasets — 53–106× faster.** And it finds a plan
*neither* single-index candidate matches: the `AND_SORTED` index intersection, which examines
101 documents rather than 50 101.

That intersection plan is the one the multi-planner ranks **last** (score 1.0001, the lowest
of the three), for two compounding reasons: `noIxisectBonus` is an explicit penalty against
`AND_SORTED`, and round-robin charges it two `work()` calls per output, halving its
productivity (51 advanced vs 101 in the same 50 102 works). The trial-period metric
penalises the best plan precisely *because* it is doing less redundant work per result.

**This scopes the finding honestly, and it is the most important caveat here.** W4 is a
defect in the mechanism that is default through 8.2, not an open unsolved problem: MongoDB's
own cost-based ranker already handles it. Per MongoDB's documentation, 8.3 makes
"multi-planning with a CBR backup" the default for eligible queries. See the counterpoints
below for why that does not make W4 vacuous.

## External evidence (JIRA + web, 2026-09-15)

Probes added to `tools/cliffhunter/mining/jira.py` (`trial-period`, `ranking-tie`, `eval-knobs`,
`productivity`, `unrepresentative`): **723 issues, 589 new to the corpus.**

### Supporting — the mechanism is independently reported

- **SERVER-40844** (2019) — *"Better tie breaking of 'perfect' indexes"*. States W4's
  mechanism in a user's own words: *"the query planner will score them equally if a given
  query runs equally 'fast' on both. **This can happen if the documents that query would
  return are located at the start of the index bounds.**"* That is the prefix-position
  argument, arrived at independently and seven years earlier. Closed **Duplicate**.
- **SERVER-14423** (2014, 7 votes, **31 watchers**) — *"Plans which fetch different numbers
  of documents can tie"*. The repro is W4 in miniature: equal `nscanned` (= works), very
  different `nscannedObjects`. This is the direct consequence of productivity dividing by a
  quantity round-robin holds constant. Open **nine years**; duped to SERVER-79400.
- **SERVER-79400** (2023, Fixed) — implemented the `docsExamined` tie-breaker, i.e. the
  `+1e-4` in `plan_ranker_util.h`. **Its own regression test uses a 111-document
  collection** — small enough that every candidate reaches EOF, which is the only regime
  where the tie-breaker can fire. On 3 M documents with the batch filling at 101, the scores
  are not tied (2.0002 vs 1.0002) and the mitigation never runs. The accepted fix is
  structurally scoped out of the regime W4 occupies.
- **SERVER-37194** (2018, 22 watchers) — *"Number of docsExamined is not considered for index
  selection"*. Independent report; same resolution.
- **SERVER-24396** (2016, **26 watchers, still Backlog after 10 years**) — *"Progressive
  elimination of candidate plans during plan ranking trial period"*. Enumerates the same
  three termination conditions we measured and proposes fixing exactly this.
- **SERVER-62981** (2022, Fixed) — makes the SBE trial period independent of collection size,
  and justifies the classic engine's looser bound thus: *"This potentially high bound of 30%
  of the collection size is not overly problematic for the classic multi-planner **because of
  its round-robin behavior**."* Round-robin is relied on to bound trial *cost* — and
  round-robin is precisely what makes `works` common across candidates and turns productivity
  into a prefix race. The property that makes the trial cheap is the property that makes it
  blind.
- **SERVER-63641** (2023, Fixed) — replaced round-robin with a priority queue *for SBE*,
  noting trial cost is order-dependent. The classic multi-planner, still the default path
  here, kept round-robin.
- **SERVER-15225 / SERVER-32452 / SERVER-77901** — the replan-on-regret machinery and its
  limits; the entry point for W5.
- **MongoDB's own architecture guide** (`src/mongo/db/exec/runtime_planners/classic_runtime_planner/README.md`)
  documents the score formula, the EOF bonus, and all three stopping conditions, and confirms
  `max(10K, 0.3 × collection_size)` for the works budget. Our measured `works` (50 102,
  51 001) and scores match it exactly.

### Counter-opinions — recorded because they constrain the claim

- **The strongest one: MongoDB documents this as accepted by design.** Same README: *"By the
  nature of this strategy, we do not have a complete guarantee that the selected plan will be
  the most optimal. It is possible that **by the nature of the data, a suboptimal plan appears
  optimal during the multiplanning trial period**. Therefore, our goal is to pick a generally
  efficient plan, which is not necessarily the most efficient plan."* W4 cannot be reported
  as a surprise. What it adds is **quantification and a rule**: the penalty is not a constant
  factor but grows with collection size (58.9× at 3 M documents, and 29 208× against the best
  available plan), it is reachable by a closed-form data condition, and no setting of the
  knob excludes it. "Generally efficient" understates a penalty that is unbounded in `N`.
- **CBR already fixes it, and 8.3 changes the default** (measured above). Counter-counter:
  the 8.3 mechanism is a *backup for when multi-planning fails* — the mixed strategy is
  literally named `NoMultiplanningResults`, and the code path triggers on *low* productivity
  (`cost_based_plan_ranking.cpp:262-268`, `bestPlanProductivity <= numResults/numWorks`).
  W4's bad plan has productivity **1.0**, the maximum possible. The fallback is aimed at the
  opposite failure mode, so W4's regime is not obviously covered by the *backup* path even in
  8.3 — though the full `automaticCE` ranker does handle it. Worth re-running on 8.3.
- **SERVER-14525** (2014, **12 votes**, 24 watchers) — *"Perf regression in 2.6.2 caused by
  not caching plans that tie during plan ranking"*. The SERVER-13675 policy that
  `docs/studies/main/patterns.md` holds up as the model class-level fix **caused a measured throughput
  regression**, because ties are common and not caching them re-runs the multi-planner on
  every query. Direct evidence that "do not persist a decision taken without discriminating
  evidence" has a real cost, and that our proposed generalisation of it must price that in.
- **A maintainer rejecting exactly this class of fix.** David Storch on SERVER-14423 (2019),
  declining a community PR to the cost formula: *"Changing our cost formula for ranking plans
  is liable to destabilize existing workloads, and should be done with extreme caution. In the
  absence of tests, it's hard for us to validate whether or not this has the intended
  performance improvement without regressing other workloads."* Any fix schema we propose has
  to answer this, and SERVER-79400's own history is the evidence: it was **merged, reverted
  the next day** for breaking `multiplanner_tie_breaking.js`, and re-landed three days later.
- **SERVER-122667** (2026, Won't Do) — planning *time* is itself a guarded budget. Our
  measurement agrees: the naive fix costs 2.0× CPU on the query it repairs.

### Web/forum search

Practitioner write-ups describe the mechanism but not the cliff: the trial period, the 101
batch, and `advanced/works` are documented in
[MongoDB's Query Plans manual](https://www.mongodb.com/docs/manual/core/query-plans/) and in
[openmymind's plan walkthrough](https://www.openmymind.net/Speedig-Up-Queries-Understanding-Query-Plans/);
[idealo's engineering post](https://medium.com/idealo-tech-blog/what-slowed-down-the-queries-mongodb-chose-the-wrong-index-b673a41af2cd)
("MongoDB Chose the Wrong Index", HTTP 403 to automated fetch, title and search summary only)
reports the productivity score selecting a slower plan in production. Community threads on
the same symptom:
[inefficient index](https://www.mongodb.com/community/forums/t/mongo-query-planner-using-inefficient-index/150828),
[wrong execution plan](https://www.mongodb.com/community/forums/t/mongodb-is-choosing-the-wrong-index-execution-plan/4660),
[perceived wrong choice](https://www.mongodb.com/community/forums/t/index-selection-perceived-wrong-choice/3441).
**No prior source found that quantifies the cliff, gives the reachability rule, or shows
invariance to the knob.** Note the asymmetry with W1: there, JIRA contained the cliff itself
(SERVER-14034); here, JIRA contains the *mechanism* (SERVER-40844, SERVER-14423) but nobody
appears to have measured what it costs or shown that the constant cannot fix it.

## Verdict

All four conditions hold. The trial period's **stopping rule** is the defect, not its scoring
formula: the full-batch condition pre-empts the EOF condition, and the EOF bonus is the only
term in the score that reflects a plan's total cost. Reachable by a closed-form data
condition, invariant to the constant, and already solved by a mechanism MongoDB ships but
does not default to before 8.3.

For `docs/studies/main/patterns.md`: this is **Pattern B** (decision on non-discriminating evidence, then
frozen) with a strictly stronger variant worth naming — *decision on **actively
misleading** evidence*. Both of MongoDB's existing Pattern B guards test for indecisive
evidence and therefore miss it.

# mongodb/works-ratchet

Plan-cache bar latches from arrival order alone: 18.5x docs, 6.5x CPU, bar stuck at 200,001 over 1,300 queries

- **Upstream:** fixed upstream in 4.1.1 (SERVER-32452) and reachable again; reported again as SERVER-77901, closed Won't Fix (<https://jira.mongodb.org/browse/SERVER-32452> <https://jira.mongodb.org/browse/SERVER-77901>)
- **Effect:** latency, strong: affected queries p50/p99 384.3/392.0 vs 2.6/3.7 ms, server CPU 10,892.7 vs 1,716.0 ms per run, peak 2,382.8 vs 2,382.5 MB; 0 vs 53 replans, by arrival order alone
- **Experiment:** W5, C1, report: [experiments/cliffs/2026-09-15-w5-works-ratchet/README.md](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/README.md)
- **Side by side with the other MongoDB latency bugs**, with where the time goes and where a timer belongs: [`docs/mongodb-latency-bugs.md`](../../../../docs/mongodb-latency-bugs.md#3-server-32452-w5-an-expensive-query-makes-wrong-plans-permanent)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** mongod 8.2.12 and mongosh 2.9.1 on PATH (tools/reproduce/get-mongodb.sh); systemd-run --user with the cgroup v2 cpu and memory controllers delegated; about 4 GB of free RAM

**Run:**

```sh
CH_PORT=15451 tools/harness/start_mongod_cgroup.sh
CH_PORT=15451 sh bugs/systems/mongodb/works-ratchet/repro/run_w5.sh my-w5
```

**Writes:** experiments/cliffs/my-w5/: env.md, raw/build.log and order.log, w5.jsonl, report.txt (per class and order), resources.txt (CPU and peak memory per order)

**Notes:** Two collections: docs (no expensive class: the control) and docs_bar (adds class M, whose works become the replan bar). Only M's position differs between M_first, M_last and M_middle. Give the run a new name (my-wN above): the recorded run's directory under experiments/cliffs/ holds its records. Pass the same CH_PORT to the start script and the run. Latency is client-side per query; CPU and peak memory are the mongod's cgroup's.

## The report

Copied from [`experiments/cliffs/2026-09-15-w5-works-ratchet/README.md`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/README.md).

### W5 — the works ratchet, probed by arrival order

> **Oracle O3 (order permutation).** Submit the same *multiset* of queries in two different
> arrival orders. A correct system reaches the same steady state and costs about the same.
> No reference implementation, no faster equivalent query, no cost model — both sides of the
> comparison are the system under test on byte-identical data. See
> `docs/oracles.md#o3--order-permutation`.

Reproduce: `bugs/systems/mongodb/works-ratchet/repro/run_w5.sh`. MongoDB 8.2.12, `planRankerMode=multiPlanning` (the default),
`internalQueryFrameworkControl=trySbeRestricted`. Host facts in [`env.md`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/env.md); records in
[`w5.jsonl`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/w5.jsonl); rendered in [`report.txt`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/report.txt); CPU and memory in
[`resources.txt`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/resources.txt).

#### The construction

**One query shape, three parameter classes.** `find({a:<int>, b:<int>})` — so every query maps to
**one** plan cache entry. Verified rather than assumed: `planCacheKey = 51C56FDD` for all three
classes. 1 000 000 documents, indexes `{a:1}` and `{b:1}`, `a=0` and `b=0` both common, everything
else rare.

| class | query | results | cheap plan | the other plan |
|---|---|---:|---|---|
| **E** | `find({a:i, b:0})`, i rare | 20 | `{a:1}` — 20 docs | `{b:1}` — **780 000 docs** |
| **H** | `find({a:0, b:j})`, j rare | 20 | `{b:1}` — 20 docs | `{a:1}` — **780 000 docs** |
| **M** | `find({a:MA, b:MB})` | 5 | either — **200 000 docs** | either — 200 000 docs |

E and H are symmetric and *conflicting*: each wants the opposite index, and getting it wrong costs
**39 000× the documents**. M is different in kind — it is a **legitimately expensive** instance of
the same shape. Nothing about M is a defect. M exists because the replan threshold is
`internalQueryCacheEvictionRatio (10.0) × decisionWorks`, and `decisionWorks` comes from whichever
instance's multi-planning promoted the cache entry:

```
E promotes the entry  ->  works =      21  ->  replan bar =       210 works
M promotes the entry  ->  works = 200 001  ->  replan bar = 2 000 010 works
```

2 000 010 works is **larger than the collection**. Once M has set the bar, no plan can ever trip it,
and a 39 000×-wrong plan for E or H becomes permanently immune to replanning. Whether M promotes
first is purely a question of **arrival order** — which is precisely what O3 perturbs.

Result sets are deliberately 20 and 5, all below 101, because W4 showed that a cached plan which
produces 101 results ends its trial with `_bestPlanChosen = true` and can never replan
(`cached_plan.cpp:122-131`). Keeping result sets small is what lets the replan machinery engage at
all, so that W5 tests the ratchet rather than re-testing W4.

#### Result 1 — the control: replanning works, and O3 still fails

Collection `docs`, four permutations of `{E×10, H×10}`, three epochs, 60 queries:

| order | docs (profiler) | docs (executor) | server ms | replans | final cache entry |
|---|---:|---:|---:|---:|---|
| alternating | 1 200 | 1 380 | **58** | **58** | `b_1`/ACTIVE w=21 |
| blocked_EH | 1 200 | 1 380 | **5** | **5** | `b_1`/ACTIVE w=21 |
| blocked_HE | 1 200 | 1 380 | **5** | **5** | `a_1`/ACTIVE w=21 |
| shuffled | 1 200 | 1 380 | 35 | 35 | `a_1`/ACTIVE w=21 |

The replan mechanism does its job here: the bar is 210 works, so the wrong plan is caught after ~210
works and the damage is capped. **Zero catastrophic queries in every order.** This is the honest
control, and it says the mechanism is not simply broken.

**But two O3 conditions still fail, and one of them is a measurement finding in its own right:**

- **Server time differs 11.6×** (58 ms vs 5 ms) for an identical multiset, because order decides
  whether the optimizer runs 58 times or 5 times.
- **Every *per-operation* work counter is identically equal.** `docsExamined` = 1 200 and the
  server-wide `queryExecutor.scannedObjects` = 1 380 in *all four* orders. A replan discards its
  trial and re-executes from a fresh executor, so **the discarded work is attributed to nothing.**
  Had this study reported `docsExamined` alone — the metric W1–W4 lean on — W5's control would have
  been recorded as order-insensitive and the effect missed completely.
- **The final cache state differs** (`a_1` vs `b_1`) across orders of the same multiset.

> **Amended 2026-09-21.** The original wording here was "every work counter is identically equal",
> and that is too strong. The SERVER-79039 reproduction found two server-wide counters that *do*
> carry the effect: `metrics.query.multiPlanner.classicWorks` (12.0×) and `classicMicros` (12.3×).
> The defensible claim is **per-operation**: `docsExamined` and `scannedObjects` are blind because
> the discarded trial belongs to no operation, but MongoDB does aggregate multi-planner work
> globally. Corrected because the overclaim is load-bearing — it is the argument for why CPU is
> required, and a reviewer with a `serverStatus` dump would catch it.
> See [`../2026-09-21-jira-repro/README.md`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/../../existing-tools/2026-09-21-jira-repro/README.md).

> The transferable lesson survives the correction: for order-dependent state, *per-operation* work
> counters are blind to the cost of decisions that are *thrown away*, and the global counters that
> do see it are not attributable to a query. CPU is the instrument that makes it legible.
> This is now condition (b) of `docs/oracles.md#o3--order-permutation`.

#### Result 2 — the cliff: a legitimate query poisons the bar for every other query

Collection `docs_bar`, four permutations of `{M×2, E×9, H×9}`, three epochs, 60 queries. **Only the
position of the two M queries differs.**

| order | docs scanned | server ms | replans | catastrophic | final cache entry |
|---|---:|---:|---:|---:|---|
| **M_first** | **22 260 540** | **11 338** | **0** | **33 / 60** | `a_1`/ACTIVE **w=200001** |
| M_last | 1 201 080 | 1 747 | 53 | 6 | `a_1`/inactive w=84 |
| M_middle | 1 201 080 | 1 708 | 52 | 6 | `b_1`/ACTIVE w=21 |
| shuffled | 1 201 080 | 1 646 | 26 | 6 | `a_1`/ACTIVE w=21 |

**18.5× the documents and 6.9× the server time, from arrival order alone.** All four O3 checks fail,
and the final state is different in all four orders.

The per-class breakdown shows where it lands — and that the aggregate understates it:

| order | E | H | M |
|---|---:|---:|---:|
| M_first | 540 docs / 27 q | **21 060 000 docs / 27 q** | 1 200 000 / 6 q |
| M_last | 540 / 27 | **540 / 27** | 1 200 000 / 6 q |

**The H class alone moves by 39 000×** — exactly the wrong-plan ratio, i.e. every single H query
runs the catastrophic plan to completion, 27 times, with `replans = 0`. The mechanism designed to
catch this did not fire once.

`M_last`'s final entry is `w=84`: the ratchet, visible directly — 21 → 42 → 84, three failed
promotions as M repeatedly measured 200 001 works against a bar the cheap class had set to 21. M's
own plan can therefore *never* be cached, so M pays full multi-planning every time. Both failure
modes — immunity and thrashing — are present in permutations of one multiset, and only the per-class
breakdown separates them.

#### Resources — CPU and peak memory, and the scoping question

From [`resources.txt`](../../../../experiments/cliffs/2026-09-15-w5-works-ratchet/resources.txt) (`bugs/systems/mongodb/works-ratchet/repro/w5_resource_cost.py`, mongod in a systemd user
cgroup, quiet mode so the state-tracing aggregations are not being priced):

| ranker | order | CPU ms | docs scanned | keys scanned | replans | peak RSS |
|---|---|---:|---:|---:|---:|---:|
| multiPlanning | **M_first** | **10 892.7** | 22 260 540 | 22 260 540 | 0 | 2382.8 MB |
| multiPlanning | M_last | 1 716.0 | 1 201 080 | 1 201 080 | 53 | 2382.5 MB |
| multiPlanning | M_middle | 1 687.8 | 1 201 080 | 1 201 080 | 52 | 2382.7 MB |
| **automaticCE** | M_first | **834.2** | **1 110** | 2 165 043 | 0 | 2382.9 MB |
| **automaticCE** | M_last | **802.2** | **1 110** | 2 102 403 | 0 | 2383.1 MB |
| **automaticCE** | M_middle | **622.8** | **1 110** | 2 133 723 | 0 | 2383.2 MB |

- **Order sensitivity: 6.5× under `multiPlanning`, 1.3× under `automaticCE`.** The cost-based ranker
  is order-insensitive, 13.1× cheaper than the worst default order, and scans 20 055× fewer
  documents.
- **Peak RSS is flat** — every row sits in 2382.5–2383.2 MB, and the spread *within* a ranker is
  0.3 MB. Order changes *which plan runs*, not what it allocates, so a flat memory column is the
  expected and correct result here. Reported as a measurement rather than assumed: the same
  sampler resolved a 6.5× CPU difference on the very same runs.
- **CBR creates no plan cache entry at all** for this shape (`-none-` in every row). That is *why*
  it is order-insensitive: the fix is structural — remove the hysteretic state from the decision
  path — not a better constant.
- CBR trades documents for keys: 1 110 docs but ~2.1M keys, because it picks the `AND_SORTED` index
  intersection for M. Same trade W4 found.

Caveat, stated rather than assumed away: peak RSS is dominated by the pinned 8 GB WiredTiger cache,
so per-query structures below a few MB are under the measurement floor.

Reproducibility: the executor scan totals came back **identical to the digit** (22 260 540 /
1 201 080 / 1 201 080) across three independent runs — the traced run, and two resource runs.

#### External evidence (JIRA + web, 2026-09-15)

Four probes added to `tools/cliffhunter/mining/jira.py` (`works-ratchet`, `inactive-entry`, `order-dependent`,
`cache-thrash`): **751 issues, 544 new to the corpus.**

##### Supporting — and the strongest support is that the fix for this *is* the mechanism

- **SERVER-32452** (2017, Fixed in 4.1.1, 2 votes, **25 watchers**) — *"Replanning may not occur
  when a plan with an extremely high `works` value is cached."* This is W5's Result 2, reported
  nine years ago. Its resolution text describes the fix as introducing inactive/active entries and
  the ×2 growth coefficient — i.e. **the ratchet we are testing is itself the fix for this exact
  failure mode.**

  W5's contribution is to show the failure mode is **still reachable, by a route the fix does not
  cover.** The guard validates a high works value by requiring it to be *reproduced* before the
  entry goes active. In `M_first` that guard is satisfied honestly: M runs twice and really does
  cost 200 001 works both times. The bar is then correct **for M** — and it is stored per query
  *shape* and applied to every parameter instance of that shape, including the two classes for which
  it is 39 000× wrong.

  > The guard asks *"is this works value reproducible?"* when the question is *"is this works value
  > representative of the shape?"* That is the same confusion as W4, one layer down — a decision
  > taken on evidence that did not generalise, then frozen.

- **SERVER-79039** (2023, **Won't Do**, 10 watchers) — *"Plan cache entries can be evicted and
  replanned continuously for certain workload patterns."* This is W5's Result 1 and the `M_last`
  thrashing, described qualitatively, including the order dependence in the reporter's own words:
  *"If the next query to activate it has a lower works value, then we'll use the new one. This puts
  us in a state where its like the higher work query never happened, and its possible to evict and
  replan again."* Closed with: *"We agree the changes to the replanning behaviour are too risky but
  in terms of diagnosability we could consider adding the original plan when a replanning happens."*
  **Known, acknowledged, explicitly declined.**
- **SERVER-98987** (2025, Fixed in **8.2.0**) — added the `serverStatus` counter for *wasteful*
  replanning, i.e. MongoDB instrumented this symptom in the very version under test. It also had to
  be reverted once before landing. The counters W5 reads (`planCache.classic.replanned`) are the
  product of this work; the project is diagnosing the problem it declined to fix.
- **SERVER-77901** (2023, Won't Fix, 10 watchers) — a community patch to cap replan works relative
  to collection size; *"in extreme cases … this replan may lose effectiveness. it may lead that the
  query use wrong index."* Same diagnosis, rejected.
- **SERVER-18777**, **SERVER-19835**, **SERVER-91156**, **SERVER-20139** — the replanning mechanism's
  scope holes and its history (not applied to rooted `$or`; subplan caching on ties; deactivate bugs
  in mixed SBE/classic mode; replanning only enabled by default in 3.0).
- **SERVER-48700** (Duplicate) — *"Add fuzz testing to ensure that the plan cache preserves query
  **correctness**."* Note the word: the plan cache has been fuzzed for correctness, never for
  performance. That is the gap O3 occupies, and it is the cleanest statement of this project's
  orthogonality claim found so far in MongoDB's own tracker.

##### Counter-opinions — recorded because they constrain the claim

- **A MongoDB engineer documents the order dependence as expected behaviour.** Franck Pachot,
  *"MongoDB Multi-Planner Optimizer and Plan Cache"* (2025-03-13): **"the first who runs determines
  the execution plan for the others"**, with a production example structurally identical to our E/H
  construction — a coffee-capsule vendor whose customer-ID queries need different indexes for retail
  customers versus shops, *"but the application obeys the 'parse one execute many' best practice."*
  So W5 is not discovering order dependence. Its contribution is **quantifying** it (18.5× docs,
  6.5× CPU, 39 000× on one class), making it a **falsifiable oracle** rather than an anecdote, and
  showing that the bar-poisoning route survives the fix that was supposed to close it.
- **`automaticCE` already fixes it, and 8.3 changes the default** (measured above). As with W4, the
  mechanism W5 attacks has a finite shelf life. Unlike W4, here the counter-counter-argument is
  weaker: CBR removes the plan cache entry entirely for this shape, so there is no order-dependent
  state left to get wrong. **This should be re-run on 8.3 before any claim about current versions.**
- **The maintainers have twice judged this area too risky to change** (SERVER-79039 "too risky";
  SERVER-77901 Won't Fix; and on SERVER-32452 David Storch: *"I'm disinclined to mess with our plan
  selection logic unless we have empirical evidence that it improves plan selection, without causing
  plan selection to regress for certain workloads."*). That is a direct instruction about what
  evidence would be actionable, and it is an argument for delivering **a workload plus a test**
  rather than a patch — the same conclusion `docs/studies/main/patterns.md` drew from W4.
- **Percona's diagnosis differs from ours, and ours is narrower.** *"MongoDB Query Plan Cache
  Explained"* attributes the replanning loop to churn: *"the re-planning loop occurs when data
  changes faster than the planner can adapt"*, with `hint()` as the workaround. W5's data is
  **completely static** — no writes during any order — and the loop still appears (52–53 replans).
  So the received explanation is not necessary: **a static collection plus a mixed parameter
  distribution is sufficient.** That is a correction to the public diagnosis, and a cheap one to
  state because it is exactly what holding the data fixed buys.

#### Verdict

O3 is violated on both collections, and the two violations are different defects:

1. **Thrashing** (control, and `M_last`): order changes how often the optimizer runs. 11.6× server
   time, **invisible in every per-operation work counter MongoDB exposes.** Known as SERVER-79039,
   Won't Do — and **reproduced on 8.2.12 on 2026-09-21**: 23 replans under an alternating order vs
   0 under a blocked one, 12.3× optimizer CPU, every per-operation counter reading 1.0×.
2. **Immunity** (`M_first`): a legitimately expensive instance of a shape sets a replan bar larger
   than the collection, and a 39 000×-wrong plan for the other parameter classes becomes permanently
   uncorrectable. 18.5× documents, 6.5× CPU. Known as SERVER-32452 — *fixed in 2018*, and reachable
   again because the fix validates reproducibility rather than representativeness.

For `docs/studies/main/patterns.md`: this is **Pattern B′** again — a decision taken on
evidence that did not generalise, then frozen — but at the level of the *replan threshold* rather
than the plan choice. W4 and W5 are the same defect in the two mechanisms that are supposed to check
each other, which is why neither catches it.

## Files

- [`repro/run_w5.sh`](repro/run_w5.sh)
- [`repro/w5_build.js`](repro/w5_build.js)
- [`repro/w5_metastable.js`](repro/w5_metastable.js)
- [`repro/w5_order.js`](repro/w5_order.js)
- [`repro/w5_report.py`](repro/w5_report.py)
- [`repro/w5_resource_cost.py`](repro/w5_resource_cost.py)

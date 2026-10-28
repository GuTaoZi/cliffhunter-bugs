# P29 mongodb-profiles — SERVER-79039 and SERVER-107471 on master, with the symptom function and its call stack

Asked for by a collaborator: reproduce one or two bugs, profile the symptom function and its call stack, give a
detailed pipeline to reproduce each, and the developer discussions. Run on 2026-10-27 in the main session. Both
bugs were first reproduced on the 8.2.12 release (N3, `experiments/existing-tools/2026-09-21-jira-repro/`); this
runs them on master and profiles the server. The ticket discussions, people named by role:
[SERVER-79039](../../../bugs/systems/mongodb/SERVER-79039/discussion.md),
[SERVER-107471](../../../bugs/systems/mongodb/SERVER-107471/discussion.md).

**Server.** Our mongod 9.1.0 built from master at 6d990baca59c: `-O2 -DNDEBUG -fno-omit-frame-pointer -g1
-march=sandybridge`, tcmalloc (buildInfo, `raw/buildinfo.json`). WiredTiger cache 8 GB, every query knob at its
default. 48 logical CPUs. The same query scripts as N3, unchanged (`bugs/systems/mongodb/SERVER-*/repro/`).

## Results

Two repetitions per arm, arms alternated (`raw/runs.jsonl`, `raw/counters.md`). "Query millis" and "docs" are the
order script's own totals; the plan-cache counters are the server's (`serverStatus().metrics.query.planCache`
and `.multiPlanner`) over the run.

| bug, arrival order | wall s | server CPU s | peak RSS MB | query millis | docs examined | cache hits | replans | multi-plannings | multi-planning s | final cache entry |
|---|---|---|---|---|---|---|---|---|---|---|
| 79039 alternating (slow) | 45.2, 44.9 | 40.7, 40.5 | 771, 810 | 38,661, 38,776 | 36,003,600 | 719 | 719 | 1,440 of 1,440 | 38.9 | inactive, works 12 |
| 79039 blocked_EC (fast) | 26.1, 25.7 | 21.3, 21.2 | 728, 811 | 20,135, 19,940 | 36,003,600 | 1,438 | 0 | 2 | 0.2 | active, works 50,001 |
| 107471 P_first (slow) | 24.7, 23.6 | 19.1, 18.6 | 753, 817 | 17,327, 16,937 | 27,164,400 | 1,798 | 0 | 2 | 0.06 | active, works 5,274, indexField1_1 |
| 107471 R_first (fast) | 18.9, 19.0 | 13.4, 13.4 | 811, 816 | 11,053, 11,169 | 3,165,600 | 1,199 | 150 | 751 | 10.4 | inactive, works 32 |

- **SERVER-79039 reproduces on master.** The same 1,440 queries examine the same 36,003,600 documents in both
  orders, but alternating them makes every query multi-plan (719 replans) and costs 1.9x the server CPU (40.6 vs
  21.2 s). The entry ends inactive at works 12 (twice the cheap class's 6) instead of active at the expensive
  class's 50,001: the cycle the ticket describes.
- **SERVER-107471 reproduces on master.** When the skip query caches its plan first, every selective query reuses
  `IXSCAN {indexField1: 1}` and examines 20,000 documents instead of 1 (24,000,000 vs 1,200 over 1,200 queries),
  with 0 replans: 8.6x the documents and 1.4x the server CPU. The fast order pays for re-planning the skip queries
  (150 replans, 10.4 s of multi-planning), which is why the CPU ratio is smaller than the read ratio.
- Peak memory does not differ (728-817 MB in every run).

## The symptom function and its call stack

perf at 499 Hz with frame-pointer call graphs on the mongod process only (`raw/shares.md`; per run
`raw/<run>.self.txt`, `.children.txt`, and folded stacks `raw/<run>.folded.gz` for a flame graph). Shares are
inclusive: samples whose stack passes through the function.

| function | 79039 alternating | 79039 blocked_EC | 107471 P_first | 107471 R_first |
|---|---|---|---|---|
| `mongo::MultiPlanStage::runTrials` (multi-planning) | **95.4%** | 1.3% | 0.4% | 79.0% |
| `mongo::CachedPlanStage::pickBestPlan` (trial of the cached plan) | 0.1% | 93.4% | **91.8%** | 0.4% |
| `mongo::FetchStage::doWork` | 92.2% | 91.5% | 83.7% | 69.5% |
| `mongo::IndexScan::doWork` | 27.7% | 27.5% | 23.6% | 21.8% |
| samples per run | 20,417, 20,331 | 10,694, 10,628 | 9,606, 9,357 | 6,749, 6,787 |

**SERVER-79039: the symptom is `mongo::MultiPlanStage::runTrials`**, multi-planning every query; in the fast order
the same work runs inside the cached plan's trial instead. Heaviest stack in the alternating order (85.5% of all
samples), outermost first, the transport frames above `handleRequest` left out:

```
mongo::ServiceEntryPointShardRole::handleRequest
mongo::(anonymous namespace)::ExecCommandDatabase::_commandExec
mongo::(anonymous namespace)::RunCommandImpl::run
mongo::CommandHelpers::runCommandInvocation
mongo::(anonymous namespace)::FindCmd::Invocation::run
mongo::getExecutorFind
mongo::exec_deferred_engine_choice::getExecutorFindDeferredEngineChoice
mongo::exec_deferred_engine_choice::planRanking
mongo::retryMakePlanner                      (catches ReplanningRequired and plans again)
mongo::exec_deferred_engine_choice::preparePlanner
mongo::plan_ranking::PlanRanker::rankPlans
mongo::plan_ranking::CBRForNoMPResultsStrategy::rankPlans
mongo::plan_ranking::CBRForNoMPResultsStrategy::resumeMultiPlannerAndPickBestPlan
mongo::classic_runtime_planner::MultiPlanner::runTrials
mongo::MultiPlanStage::runTrials
  -> MultiPlanStage::workAllPlans -> FetchStage::doWork / IndexScan::doWork -> WiredTiger
     (__wt_row_search 6.4%, __row_search_warm_leaf_candidates 6.4%, __wt_btcur_next 6.0%, ... of its samples)
```

The fast order's stack ends instead in `preparePlanner -> classic_runtime_planner::ClassicPlannerInterface::plan ->
CachedPlanner::doPlan -> CachedPlanStage::pickBestPlan`.

**SERVER-107471: the symptom is `mongo::CachedPlanStage::pickBestPlan`**, the trial run of the wrongly cached plan,
which here does all of the selective query's scanning and is never rejected. Heaviest stack in P_first (91.8% of
all samples): the same frames down to `preparePlanner`, then

```
mongo::classic_runtime_planner::ClassicPlannerInterface::plan
mongo::classic_runtime_planner::CachedPlanner::doPlan
mongo::CachedPlanStage::pickBestPlan
  -> PlanStage::work -> FetchStage::doWork -> IndexScan::doWork over indexField1_1 -> WiredTiger
     (__wt_row_search 6.0%, __row_search_warm_leaf_candidates 5.7%, __wt_btcur_next 5.3%, ... of its samples)
```

## The deciding code (master, 6d990baca59c)

Paths under `src/mongo/db/`; read from the source and checked against these runs.

- The trial of a cached plan: `exec/classic/cached_plan.cpp:75` sets `maxWorksBeforeReplan =
  internalQueryCacheEvictionRatio (10) x decisionWorks`; the loop at `:87` ends without replanning when enough
  results came back (`:122`) or the scan reached EOF (`:127`); only a loop that runs out (`:150`) logs "Evicting cache
  entry and replanning query" and calls `replan()`, which deactivates the entry.
- The entry's state: `query/plan_cache/plan_cache.h:675-762` (`getNewEntryState`). An active entry is replaced only
  when the new works are not greater (`:709`); an inactive one whose new works are greater stays inactive with its
  works grown to `max(old + 1, old x internalQueryCacheWorksGrowthCoefficient (2))` (`:724-738`); one whose new works
  are not greater is promoted to active at the new, lower works (`:758`).
- SERVER-79039 is these two together: an expensive query exceeds 10x the cheap works and deactivates the entry,
  the next cheap query finds it inactive, multi-plans, and promotes it back at its own low works, and the expensive
  query overshoots again. Arriving in blocks, the expensive class grows the works until the entry holds 50,001 and
  stays active.
- SERVER-107471: the plan cache key, `query/canonical_query_encoder.cpp:1281` (`encodeClassic`), does not encode
  skip or limit (`encodeLimitSkip`, `:732`, is not on that path), so the skip query and the selective query share an
  entry. The skip query's plan is cached with works 5,274; the selective query's trial reaches EOF after 20,000
  documents, inside the 52,740-works bound, so it counts as efficient (`cached_plan.cpp:127`) and is never replanned.

To watch the events directly: `db.docs.aggregate([{$planCacheStats: {}}])` (fields `isActive`, `works`, `cachedPlan`),
`db.serverStatus().metrics.query.planCache.classic` (`hits`, `misses`, `replanned`), and with
`db.setProfilingLevel(0, {slowms: 0})` the slow-query log's `replanned`, `replanReason`, `fromPlanCache`,
`planCacheKey` and `docsExamined` per query.

## How to run it

Needs: a mongod built with frame pointers (`-fno-omit-frame-pointer`, the default of MongoDB's own build; check
`buildInfo().buildEnvironment.ccflags`, or record with `--call-graph dwarf` instead), mongosh 2.9.1, perf
(here from `nix-shell -p perf`, 7.2.5), a systemd user session with the cgroup v2 cpu and memory controllers
delegated, `kernel.perf_event_paranoid` at most 1 (here 1: a user may profile its own processes), python3, about
4 GB of free RAM. About 9 minutes for two repetitions.

```sh
# 1. All of it in one go: start mongod, load the data, run and profile each arm, two repetitions
MONGOD=/path/to/mongod MONGOD_LIBS=/dir/of/its/libstdc++ \
  flock $CLIFF_DATA/locks/machine.lock sh tools/probes/mongo_profile/profile.sh 2
# 2. Tables
python3 tools/probes/mongo_profile/counters.py "$OUT"          # the counters table above
python3 tools/probes/mongo_profile/shares.py "$OUT" > "$OUT/shares.md"   # shares, stacks, hottest leaves
# 3. A flame graph of one run (flamegraph.pl from the FlameGraph repository, or open the file in speedscope.app)
flamegraph.pl "$OUT/s79039-alternating-r1.folded" > s79039-alternating.svg
```

`MONGOD_LIBS` is only needed for a mongod that does not find its C++ runtime by itself (ours, built with Nix,
needs gcc 14's lib directory); `OUT` defaults to `$CLIFF_DATA/repro/mongodb-profiles/out`. What `profile.sh`
does, step by step:

1. Starts mongod in a systemd user unit, `mongod-prof`, port 15451, fresh dbpath, `--wiredTigerCacheSizeGB 8`, so
   that its CPU (`cpu.stat`) and memory are its own; saves `buildInfo`.
2. Loads the data with the N3 scripts: `s79039_build.js` (1,000,000 documents in `ch_s79039.docs`, indexes `a_1`
   and `b_1`) and `s107471_build.js` (1,000,000 documents in `ch_s107471.docs`, indexes `indexField1_1` and
   `indexField10_1`).
3. For each arm: `perf record -F 499 -g -p <mongod pid>`, then one arrival order alone through the N3 order script:
   SERVER-79039 with `S2_ORDERS=alternating` or `blocked_EC` and `S2_EPOCHS=120` (1,440 queries: per epoch 6 cheap
   and 6 expensive ones of one query shape); SERVER-107471 with `S1_ORDERS=P_first` or `R_first`, `S1_SKIP=5000`,
   `S1_EPOCHS=150` (1,800 queries: per epoch 4 skip queries and 8 selective ones of one shape). Each order script
   resets the plan cache first. Then perf stops; the wall time, the cgroup's CPU and the process's peak RSS
   (`VmHWM` after `clear_refs`) go to `runs.jsonl`, and `perf report` and the folded stacks to one file each.
4. Arms alternate between repetitions (slow first in the first, fast first in the second).

The N3 scripts also run the whole recorded experiment without perf (`run_s79039.sh`, `run_s107471.sh`; see each
bug's README).

## Files

- `tools/probes/mongo_profile/`: `profile.sh`, `fold.py` (perf script to folded stacks), `counters.py`, `shares.py`
- `data/experiments/mongodb-profiles/raw/`: `runs.jsonl`, `counters.md`, `shares.md`, `buildinfo.json`, per run the
  order script's log (`.log.gz`, with every query's trace), `perf report` outputs (`.self.txt`, `.children.txt`) and
  folded stacks (`.folded.gz`), `session.log`. The `perf.data` files (30 MB) stay in the data root.

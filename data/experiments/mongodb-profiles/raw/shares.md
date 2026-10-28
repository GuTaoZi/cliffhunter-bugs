# Where the server's CPU goes, slow vs fast arrival order (perf, 499 Hz, frame-pointer call graphs)

Inclusive share of all samples of the mongod process whose stack passes through the function; mean of the repetitions. A sample counts once per row even if the function recurs.

## s79039: alternating (slow) vs blocked_EC (fast)

samples per run: alternating [20417, 20331], blocked_EC [10694, 10628]

| function | alternating | blocked_EC | samples alternating / blocked_EC |
|---|---|---|---|
| multi-planning: MultiPlanStage::runTrials | 95.4% | 1.3% | 136.3x |
|   candidate trials: MultiPlanStage::workAllPlans | 95.2% | 1.3% | 137.1x |
| cached-plan trial: CachedPlanStage::pickBestPlan | 0.1% | 93.4% | 0.0x |
| plan ranking (CBR then multi-planning): PlanRanker::rankPlans | 95.7% | 1.3% | 136.8x |
| classic IndexScan::doWork | 27.7% | 27.5% | 1.9x |
| classic FetchStage::doWork | 92.2% | 91.5% | 1.9x |

Heaviest stack down to `MultiPlanStage::runTrials` in alternating (85.5% of samples; outermost first, the transport and future frames above handleRequest left out):

```
  mongo::ServiceEntryPointShardRole::handleRequest()
  mongo::(anonymous namespace)::ExecCommandDatabase::_commandExec()
  mongo::(anonymous namespace)::RunCommandImpl::run()
  mongo::CommandHelpers::runCommandInvocation()
  mongo::(anonymous namespace)::FindCmd::Invocation::run()
  mongo::getExecutorFind()
  mongo::exec_deferred_engine_choice::getExecutorFindDeferredEngineChoice(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mong
  mongo::exec_deferred_engine_choice::planRanking(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mongo::CanonicalQuery, std::
  mongo::retryMakePlanner(std::unique_ptr<mongo::QueryPlannerParams, std::default_delete<mongo::QueryPlannerParams> >, std::function<std::unique_ptr<mongo::QueryP
  std::_Function_handler<std::unique_ptr<mongo::PlannerInterface, std::default_delete<mongo::PlannerInterface> >
  mongo::exec_deferred_engine_choice::preparePlanner()
  mongo::plan_ranking::PlanRanker::rankPlans()
  mongo::plan_ranking::CBRForNoMPResultsStrategy::rankPlans()
  mongo::plan_ranking::CBRForNoMPResultsStrategy::resumeMultiPlannerAndPickBestPlan()
  mongo::classic_runtime_planner::MultiPlanner::runTrials()
  mongo::MultiPlanStage::runTrials()
```

Hottest functions (self samples) under it, share of its 38858 samples:

- 6.4% `__wt_row_search`
- 6.4% `__row_search_warm_leaf_candidates`
- 6.0% `__wt_btcur_next`
- 3.7% `__wt_row_leaf_key.constprop.0`
- 3.6% `mongo::WiredTigerRecordStoreCursorBase::seekExactCommon`
- 3.1% `mongo::WorkingSetCommon::fetch`
- 3.0% `__wt_lex_compare_short.isra.0`
- 2.9% `__wt_btcur_search`
- 2.9% `__wt_txn_read`
- 2.7% `mongo::IndexScan::doWork`

Heaviest stack down to `CachedPlanStage::pickBestPlan` in blocked_EC (93.4% of samples; outermost first, the transport and future frames above handleRequest left out):

```
  mongo::ServiceEntryPointShardRole::handleRequest()
  mongo::(anonymous namespace)::ExecCommandDatabase::_commandExec()
  mongo::(anonymous namespace)::RunCommandImpl::run()
  mongo::CommandHelpers::runCommandInvocation()
  mongo::(anonymous namespace)::FindCmd::Invocation::run()
  mongo::getExecutorFind()
  mongo::exec_deferred_engine_choice::getExecutorFindDeferredEngineChoice(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mong
  mongo::exec_deferred_engine_choice::planRanking(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mongo::CanonicalQuery, std::
  mongo::retryMakePlanner(std::unique_ptr<mongo::QueryPlannerParams, std::default_delete<mongo::QueryPlannerParams> >, std::function<std::unique_ptr<mongo::QueryP
  std::_Function_handler<std::unique_ptr<mongo::PlannerInterface, std::default_delete<mongo::PlannerInterface> >
  mongo::exec_deferred_engine_choice::preparePlanner()
  mongo::classic_runtime_planner::ClassicPlannerInterface::plan()
  mongo::classic_runtime_planner::CachedPlanner::doPlan()
  mongo::CachedPlanStage::pickBestPlan()
```

Hottest functions (self samples) under it, share of its 19911 samples:

- 6.9% `__row_search_warm_leaf_candidates`
- 6.3% `__wt_row_search`
- 5.4% `__wt_btcur_next`
- 3.8% `__wt_row_leaf_key.constprop.0`
- 3.5% `mongo::WiredTigerRecordStoreCursorBase::seekExactCommon`
- 3.3% `__wt_lex_compare_short.isra.0`
- 3.1% `mongo::WorkingSetCommon::fetch`
- 2.9% `__wt_btcur_search`
- 2.8% `__wt_txn_read`
- 2.6% `mongo::IndexScan::doWork`

## s107471: P_first (slow) vs R_first (fast)

samples per run: P_first [9606, 9357], R_first [6749, 6787]

| function | P_first | R_first | samples P_first / R_first |
|---|---|---|---|
| multi-planning: MultiPlanStage::runTrials | 0.4% | 79.0% | 0.0x |
|   candidate trials: MultiPlanStage::workAllPlans | 0.4% | 78.8% | 0.0x |
| query planning: QueryPlanner::plan | 0.0% | 0.7% | 0.0x |
| cached-plan trial: CachedPlanStage::pickBestPlan | 91.8% | 0.4% | 334.7x |
| plan ranking (CBR then multi-planning): PlanRanker::rankPlans | 0.4% | 84.1% | 0.0x |
| classic IndexScan::doWork | 23.6% | 21.8% | 1.5x |
| classic FetchStage::doWork | 83.7% | 69.5% | 1.7x |

Heaviest stack down to `CachedPlanStage::pickBestPlan` in P_first (91.8% of samples; outermost first, the transport and future frames above handleRequest left out):

```
  mongo::ServiceEntryPointShardRole::handleRequest()
  mongo::(anonymous namespace)::ExecCommandDatabase::_commandExec()
  mongo::(anonymous namespace)::RunCommandImpl::run()
  mongo::CommandHelpers::runCommandInvocation()
  mongo::(anonymous namespace)::FindCmd::Invocation::run()
  mongo::getExecutorFind()
  mongo::exec_deferred_engine_choice::getExecutorFindDeferredEngineChoice(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mong
  mongo::exec_deferred_engine_choice::planRanking(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mongo::CanonicalQuery, std::
  mongo::retryMakePlanner(std::unique_ptr<mongo::QueryPlannerParams, std::default_delete<mongo::QueryPlannerParams> >, std::function<std::unique_ptr<mongo::QueryP
  std::_Function_handler<std::unique_ptr<mongo::PlannerInterface, std::default_delete<mongo::PlannerInterface> >
  mongo::exec_deferred_engine_choice::preparePlanner()
  mongo::classic_runtime_planner::ClassicPlannerInterface::plan()
  mongo::classic_runtime_planner::CachedPlanner::doPlan()
  mongo::CachedPlanStage::pickBestPlan()
```

Hottest functions (self samples) under it, share of its 17404 samples:

- 6.0% `__wt_row_search`
- 5.7% `__row_search_warm_leaf_candidates`
- 5.3% `__wt_btcur_next`
- 3.8% `__wt_search_insert`
- 3.4% `mongo::WiredTigerRecordStoreCursorBase::seekExactCommon`
- 2.9% `__wt_row_leaf_key.constprop.0`
- 2.7% `__wt_btcur_search`
- 2.7% `__wt_lex_compare_short.isra.0`
- 2.7% `mongo::WorkingSetCommon::fetch`
- 2.6% `mongo::IndexScan::doWork`

Heaviest stack down to `MultiPlanStage::runTrials` in R_first (78.9% of samples; outermost first, the transport and future frames above handleRequest left out):

```
  mongo::ServiceEntryPointShardRole::handleRequest()
  mongo::(anonymous namespace)::ExecCommandDatabase::_commandExec()
  mongo::(anonymous namespace)::RunCommandImpl::run()
  mongo::CommandHelpers::runCommandInvocation()
  mongo::(anonymous namespace)::FindCmd::Invocation::run()
  mongo::getExecutorFind()
  mongo::exec_deferred_engine_choice::getExecutorFindDeferredEngineChoice(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mong
  mongo::exec_deferred_engine_choice::planRanking(mongo::OperationContext*, mongo::MultipleCollectionAccessor const&, std::unique_ptr<mongo::CanonicalQuery, std::
  mongo::retryMakePlanner(std::unique_ptr<mongo::QueryPlannerParams, std::default_delete<mongo::QueryPlannerParams> >, std::function<std::unique_ptr<mongo::QueryP
  std::_Function_handler<std::unique_ptr<mongo::PlannerInterface, std::default_delete<mongo::PlannerInterface> >
  mongo::exec_deferred_engine_choice::preparePlanner()
  mongo::plan_ranking::PlanRanker::rankPlans()
  mongo::plan_ranking::CBRForNoMPResultsStrategy::rankPlans()
  mongo::classic_runtime_planner::MultiPlanner::runTrials()
  mongo::MultiPlanStage::runTrials()
```

Hottest functions (self samples) under it, share of its 10694 samples:

- 6.0% `__wt_btcur_next`
- 5.9% `__wt_row_search`
- 5.7% `__row_search_warm_leaf_candidates`
- 3.2% `mongo::WiredTigerRecordStoreCursorBase::seekExactCommon`
- 3.2% `__wt_row_leaf_key.constprop.0`
- 2.7% `mongo::WorkingSetCommon::fetch`
- 2.6% `__wt_btcur_search`
- 2.6% `__wt_txn_read`
- 2.5% `__wt_compare_bounds`
- 2.3% `mongo::IndexScan::doWork`


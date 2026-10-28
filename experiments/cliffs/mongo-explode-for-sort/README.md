# W12 mongo/explode-for-sort: a one-parameter sweep finds the planner's cliff from outside

The main branch's MongoDB item W1 (`bugs/tables/imports/mongo-main-items.tsv`): for `find({a: {$in: [...]}}).sort({b: 1})`
on an index {a: 1, b: 1}, the planner explodes the query into one index scan per `$in` value merged in sort order
while the number of scans is at most `internalQueryMaxScansToExplode` (200;
`src/mongo/db/query/planner_analysis.cpp:1365-1376` at 6d990ba, a decision our finder calls heuristic); above it, it
scans every matching key and sorts. Main measured it on MongoDB 8.2.12. Here it is reproduced on our own release
build of 6d990ba with a plain sweep of one workload parameter, with no probes and no rebuild.

**Build.** `tools/mongo/mongo_build.sh` (mongod 9.1.0 at 6d990ba; flags read from the running server's buildInfo:
`-O2 -DNDEBUG`). **Data.** 1,000,000 documents `{_id: i, a: i % 250, b: i}` and the index {a: 1, b: 1}, loaded in
6.2 s. **Workload.** The query above with `$in` = the first N values of a and `limit 10`, for N in 100, 150, 190, 199,
200, 201, 202, 210, 250; per point, explain's executionStats, then 5 timed queries (median), the server's CPU over
those 5 and its peak RSS. All points interleaved, 3 repetitions, each in a new shuffled order. `run.py`; raw output
`raw/runs.jsonl`, `summary.json`. Whole run: 40.7 s wall; server peak RSS 471.4 MB.

| N ($in values) | plan | keys examined | latency, median of 3 (ms) | server CPU for 5 queries (s) |
|---|---|---|---|---|
| 100 | SORT_MERGE | 109 | 0.66 | 0.00 |
| 190 | SORT_MERGE | 199 | 1.11 | 0.01 |
| 199 | SORT_MERGE | 208 | 1.12 | 0.01 |
| 200 | SORT_MERGE | 209 | 1.17 | 0.00 |
| **201** | **IXSCAN + blocking SORT** | **804,001** | **431.06** | **2.17** |
| 202 | IXSCAN + blocking SORT | 808,001 | 432.27 | 2.17 |
| 210 | IXSCAN + blocking SORT | 840,001 | 449.32 | 2.26 |
| 250 | IXSCAN + blocking SORT | 1,000,000 | 535.97 | 2.68 |

One more `$in` value, 200 → 201, examines 3,847x the keys and takes 368x as long (1.17 → 431.06 ms); key counts were
identical in all three repetitions and latencies within 0.6%. The cliff sits exactly at the constant in the decision
the finder flagged. A rediscovery of main's W1 on another version (main: 219 → 5,025,001 keys, 436x latency on
8.2.12), not a new bug. What it shows: once the threshold and the workload parameter that drives it are known, a
sweep of that one parameter finds and measures the cliff in under a minute, with an unmodified release build.

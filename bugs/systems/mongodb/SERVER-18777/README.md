# mongodb/SERVER-18777

Reproduced on the 8.2.12 release: a rooted $or's branch plan cached for one parameter class serves the other with no trial or replan; that class's queries take 143 vs 1-2 ms (280,000 vs 20 documents), in every arrival order, 0 replans; with the trial (whole-$or caching, or the branch alone) 1-3 ms; server CPU 10.3 vs 0.16 s per pass, memory equal

- **Upstream:** open upstream (SERVER-18777, Backlog since 2015)
- **Effect:** latency, strong: a rooted $or's cached branch plan serves the other parameter class: 143 vs 1-2 ms per query, never replanned; server CPU 10.3 vs 0.16 s per pass, memory equal
- **Experiment:** P36, report: [experiments/reproductions/mongodb-SERVER-18777/README.md](../../../../experiments/reproductions/mongodb-SERVER-18777/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** mongod 8.2.12 and mongosh 2.9.1 on PATH (tools/reproduce/get-mongodb.sh); systemd-run --user with the cgroup v2 cpu and memory controllers delegated; about 5 GB of free RAM

**Run:**

```sh
python3 bugs/systems/mongodb/SERVER-18777/repro/run.py measure 3
python3 bugs/systems/mongodb/SERVER-18777/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended; traced and quiet passes), repro/data/buildinfo.json, repro/logs/build.log, repro/results.md

**Minutes:** about 2

**Notes:** run.py starts its own mongod (tools/harness/start_mongod_cgroup.sh, unit mongod-s18777, port 15452, data under $CLIFF_DATA/mongo-s18777), loads the 300,000 documents, runs every arm and stops the unit. There is no fix to compare: the arms are the default (orjoin) and two ways of planning the same queries with the cached-plan trial (whole, plain). report averages every row of data/runs.jsonl: delete it before a re-run.

## The report

Copied from [`experiments/reproductions/mongodb-SERVER-18777/README.md`](../../../../experiments/reproductions/mongodb-SERVER-18777/README.md).

### P36 mongodb-SERVER-18777 — a rooted $or's branch plans are cached without a trial

Queue rank 31 of `bugs/tables/queue.tsv` (severity 4.5, relevance 4, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/mongodb/SERVER-18777/repro/`; raw data: `data/experiments/mongodb-SERVER-18777/raw/`.

**The bug.** MongoDB plans a rooted `$or` branch by branch (subplanning, on by default: `internalQueryPlanOrChildrenIndependently`, `src/mongo/db/exec/subplan.h:100-103` at r8.2.12) and caches each branch's plan under the branch's own shape. When a branch's shape has an active cache entry, the planner takes the cached index tags as they are (`src/mongo/db/query/query_planner.cpp:2040-2052` and `1878-1884`, through `getSolutionCachedData`, `src/mongo/db/exec/subplan.cpp:189-204`). Nothing runs a trial on that branch plan. A whole query's cached plan goes through `CachedPlanStage`, which gives it a trial of `internalQueryCacheEvictionRatio` (10) × its recorded works and replans it when the trial is exceeded (`src/mongo/db/exec/cached_plan.cpp:102-108`, `177-195`). A branch plan cached for one parameter class is therefore used for every other class of the same shape, however bad it is, and is never replanned or evicted. Open upstream as SERVER-18777 (Backlog since 2015).

**Server.** The MongoDB 8.2.12 release binary (`buildInfo`: version 8.2.12, gitVersion 0f912e80210b, `debug: false`, tcmalloc; the cited lines are at the `r8.2.12` tag, 10d50f5046de, of the public repository, which does not hold the release build's own commit). One `mongod` (WiredTiger cache 4 GB, port 15452) ran in a systemd user unit (`tools/harness/start_mongod_cgroup.sh`), so its CPU (`cpu.stat` `usage_usec`) and peak memory (`memory.peak`, reset before each pass) are the server's alone. Classic engine (`internalQueryFrameworkControl` `trySbeRestricted`).

**Data** (`s18777_build.js`). 300,000 documents `{a, b, c, pad}`, with indexes on `a`, `b` and `c`. Per step v = 1..1000: 20 `{a: v, b: 0}`, 130 filler `{a: 0, b: 0}`, 20 `{a: 0, b: v}`, 130 filler. So `a: 0` and `b: 0` each match 280,000 documents, and `c` is unique. Class A, `{a: i, b: 0}`, is 20 documents through IXSCAN{a} and 280,000 through IXSCAN{b}; class B, `{a: 0, b: j}`, is the mirror image.

**Arms** (`s18777_order.js`), all the same query shape with fresh parameters per query:
- `orjoin`: `find({$or: [{a: X, b: Y}, {c: K}]})`, the default. Branches are subplanned and the first branch's plan is cached per branch shape. This is the bug.
- `whole`: the same query with `internalQueryPlanOrChildrenIndependently=false`. The whole `$or` is cached, with the trial. A control.
- `plain`: the branch alone, `find({a: X, b: Y})`. A cached plan with the trial. A control.

Six arrival orders per arm, with the plan cache cleared before each:
- `alternating`, `blocked_AB`, `blocked_BA` and `shuffled`: 6 A and 6 B queries per epoch, 3 epochs, 36 queries;
- `pair_AAB` and `pair_BBB`: the same final B query after two A queries or after two B queries.

Each arm ran a traced pass (profiler and `$planCacheStats`: documents examined, plan and cache state per query) and a quiet pass (latency only). There were 3 repetitions, with the arm order rotated, under the machine lock.

**Results** (quiet passes, per-class median wall time per query, mean over 3 repetitions; slow means more than 100,000 documents examined, from the traced passes; `results.md`):

| order | orjoin A | orjoin B | slow (of 18 per class) | whole A / B | plain A / B | replans orjoin / whole |
|---|---|---|---|---|---|---|
| alternating | 143.2 ms | 2.1 ms | A 17 | 1.8 / 1.8 ms | 1.3 / 1.3 ms | 0 / 34 |
| blocked_AB | 1.8 ms | 143.3 ms | B 18 | 1.0 / 1.0 ms | 0.8 / 0.8 ms | 0 / 5 |
| blocked_BA | 143.1 ms | 1.7 ms | A 18 | 1.1 / 1.1 ms | 0.9 / 0.9 ms | 0 / 5 |
| shuffled | 143.3 ms | 2.2 ms | A 17 | 2.0 / 1.6 ms | 1.6 / 1.4 ms | 0 / 17 |
| pair_AAB | 2.4 ms | 154.1 ms | B 1 (of 1) | 2.1 / 2.5 ms | 1.7 / 2.7 ms | 0 / 1 |
| pair_BBB | | 2.0 ms | 0 | 1.9 ms | 1.6 ms | 0 / 0 |

| per quiet pass (all six orders) | orjoin | whole | plain |
|---|---|---|---|
| server CPU | 10.29 s | 0.16 s | 0.13 s |
| queries' total wall time | 10.47 s | 0.23 s | 0.18 s |
| server peak memory | 269 MB | 269 MB | 269 MB |

The first class to arrive decides the branch plan for the whole run. In `orjoin` it is cached on the first queries (two multi-plannings per order, one per branch) and kept: every query of the other class examines 280,000 documents instead of 20 and takes about 143 ms instead of 1-2 ms, and no query is ever replanned. The minimal pair shows it directly: the same B query takes 2.0 ms after two B queries and 154 ms after two A queries. With the trial in place, in both controls, a misplanned query exceeds its trial and is replanned (34 replans in 36 alternating queries), so every query stays at 1-3 ms. The bug costs 64 times the server CPU for the same queries, with the same memory. It is in latency, and it is decided by arrival order alone.

## Files

- [`repro/run.py`](repro/run.py)
- [`repro/s18777_build.js`](repro/s18777_build.js)
- [`repro/s18777_order.js`](repro/s18777_order.js)

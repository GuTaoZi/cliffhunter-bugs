# mongodb/explode-for-sort

Explode-for-sort cap: 22,945x work for one extra $in element

- **Upstream:** fixed upstream in 2014 by raising the cap from 50 to 200 (SERVER-14034); the same cliff at 201 (<https://jira.mongodb.org/browse/SERVER-14034>)
- **Effect:** latency, strong: 4.61 to 359.51 ms (78x) and 4,589x the keys from 200 to 201 $in values; on our build of master, server CPU 0.00 to 2.17 s per 5 queries, peak 471.4 MB
- **Experiment:** W1, W12, I2, I3, I5, I6, I7, report: [experiments/cliffs/2026-09-15-w1-explode-for-sort/README.md](../../../../experiments/cliffs/2026-09-15-w1-explode-for-sort/README.md)
- **Side by side with the other MongoDB latency bugs**, with where the time goes and where a timer belongs: [`docs/mongodb-latency-bugs.md`](../../../../docs/mongodb-latency-bugs.md#5-server-14034-w1-explode-for-sort-cap)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** mongod 8.2.12 and mongosh 2.9.1 on PATH (tools/reproduce/get-mongodb.sh); systemd-run --user with the cgroup v2 cpu and memory controllers delegated; about 4 GB of free RAM; for the CPU and memory run, a mongod built from master (6d990ba here)

**Run:**

```sh
CH_PORT=15451 tools/harness/start_mongod_cgroup.sh
CH_PORT=15451 sh bugs/systems/mongodb/explode-for-sort/repro/run_w1.sh my-w1
MONGOD=/path/to/mongod python3 bugs/systems/mongodb/explode-for-sort/repro/run.py --port=15450
```

**Writes:** experiments/cliffs/my-w1/: env.md, raw/, w1-n2000000.jsonl, report-n2000000.txt (median ms and keys per $in length); run.py starts its own mongod and writes raw/runs.jsonl and summary.json next to itself

**Notes:** W1_N sets the collection size (default 2,000,000). The 8.2.12 run records latency only; run.py adds the server's CPU and peak RSS (W12). The W1 README's headline (5,025,001 keys, about 2,050 ms) is from a larger run with no committed record; report.txt holds the numbers. MONGOD_LIBS names a library directory if that mongod needs one. Give the run a new name (my-wN above): the recorded run's directory under experiments/cliffs/ holds its records. Pass the same CH_PORT to the start script and the run. Latency is client-side per query; CPU and peak memory are the mongod's cgroup's.

## The report

Copied from [`experiments/cliffs/2026-09-15-w1-explode-for-sort/README.md`](../../../../experiments/cliffs/2026-09-15-w1-explode-for-sort/README.md).

### W1 — explode-for-sort cap (the primary run)

**Site:** `internalQueryMaxScansToExplode = 200` · **Oracle:** O1 (workload continuity)

One `$in` element across the bound. At `|$in| = 200` the planner explodes the `$in` into per-value
index scans and merges them (`SORT_MERGE`); at 201 it gives up and takes a blocking `SORT`.

| `k` | plan | keys examined | median ms |
|---|---|---|---|
| 199 | `LIMIT>FETCH>SORT_MERGE>IXSCAN…` | 218 | 4.62 |
| 200 | same | 219 | ~4.7 |
| **201** | `…SORT` (blocking) | **5 025 001** | **~2 050** |

**22 945× work, 436× latency, for one extra `$in` element.** Full numbers in `report.txt`;
`noise-floor.jsonl` is the 30-repeat baseline establishing that ~0.1 rsd is the measurement floor,
so the cliff is four orders of magnitude above noise.

Orientation: `docs/workload-atlas.md`.
Note that N1 later found **BFA already catches W1** (155×) — see
`../2026-09-16-h2-oracle-coverage/`. W1's lasting
value is not novelty; it is SERVER-14034, which reported this same cliff in 2014 when the limit
was 50, was "fixed" by raising it to 200, and is reachable again at 201.

## Files

- [`repro/noise_floor.js`](repro/noise_floor.js)
- [`repro/run.py`](repro/run.py)
- [`repro/run_w1.sh`](repro/run_w1.sh)
- [`repro/w1_build.js`](repro/w1_build.js)
- [`repro/w1_fanout_crossover.js`](repro/w1_fanout_crossover.js)
- [`repro/w1_limit_crossover.js`](repro/w1_limit_crossover.js)
- [`repro/w1_sweep.js`](repro/w1_sweep.js)
- [`repro/w1_threshold_invariance.js`](repro/w1_threshold_invariance.js)

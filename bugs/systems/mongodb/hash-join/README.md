# mongodb/hash-join

Hash-join eligibility bound: 1,667x work and 145x CPU to save 0 MB

- **Upstream:** a server parameter (internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000), no ticket
- **Effect:** latency, strong: 11.41 to 2,479.86 ms (217x) from 10,000 to 10,001 foreign documents, CPU 19.1 vs 2,758.4 ms per query; the hash table is under 1 MB
- **Experiment:** W2, I2, I8, report: [experiments/cliffs/2026-09-15-w2-hash-join/README.md](../../../../experiments/cliffs/2026-09-15-w2-hash-join/README.md)
- **Side by side with the other MongoDB latency bugs**, with where the time goes and where a timer belongs: [`docs/mongodb-latency-bugs.md`](../../../../docs/mongodb-latency-bugs.md#4-hash-join-eligibility-bound-w2)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** mongod 8.2.12 and mongosh 2.9.1 on PATH (tools/reproduce/get-mongodb.sh); systemd-run --user with the cgroup v2 cpu and memory controllers delegated; about 4 GB of free RAM

**Run:**

```sh
CH_UNIT=mongod-capped CH_PORT=15451 tools/harness/start_mongod_cgroup.sh
CH_PORT=15451 sh bugs/systems/mongodb/hash-join/repro/run_w2.sh my-w2
CH_PORT=15451 CH_UNIT=mongod-capped python3 bugs/systems/mongodb/hash-join/repro/w2_resource_cost.py
```

**Writes:** experiments/cliffs/my-w2/: env.md, raw/, w2.jsonl, report.txt (median ms and documents examined per foreign size); the resource script prints CPU per query for the hash join, the nested loop and the bound raised

**Notes:** The resource script reads the unit's cgroup, so mongod runs under CH_UNIT=mongod-capped for both steps. Its peak-memory column is not a per-run peak on kernels that ignore a write to memory.peak (6.18 here): the hash table is under 1 MB either way. Give the run a new name (my-wN above): the recorded run's directory under experiments/cliffs/ holds its records. Pass the same CH_PORT to the start script and the run. Latency is client-side per query; CPU and peak memory are the mongod's cgroup's.

## The report

Copied from [`experiments/cliffs/2026-09-15-w2-hash-join/README.md`](../../../../experiments/cliffs/2026-09-15-w2-hash-join/README.md).

### W2 — hash-join eligibility bound

**Site:** `internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000` · **Oracle:** O1

One document across the bound decides `$lookup`'s join algorithm.

| foreign docs | join | docs examined | median ms |
|---|---|---|---|
| 10 000 | `HASH_LOOKUP` | 12 000 | 11.4 |
| **10 001** | `NESTED_LOOP` | **20 004 000** | **2 479.9** |

**1 667× work, 217× latency, 145× CPU — to save 0 MB.** The bound is a *memory* guard, but the
hash table at 10 001 documents is under a megabyte; the guard conditions on document count while
the outcome is governed by cost. Resource accounting in
[`../2026-09-15-w2-resource-cost/`](../../../../experiments/cliffs/2026-09-15-w2-hash-join/../../instruments/2026-09-15-w2-resource-cost/README.md).

Same shape as W1 (a resource bound gating a strategy switch, site class 1).

## Files

- [`repro/run_w2.sh`](repro/run_w2.sh)
- [`repro/w2_build.js`](repro/w2_build.js)
- [`repro/w2_crossover.js`](repro/w2_crossover.js)
- [`repro/w2_crossover_indexed.js`](repro/w2_crossover_indexed.js)
- [`repro/w2_resource_cost.py`](repro/w2_resource_cost.py)
- [`repro/w2_sweep.js`](repro/w2_sweep.js)

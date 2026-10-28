# cliffhunter-bugs

Reproduced performance bugs in Redis, Valkey, memcached, PostgreSQL, RocksDB and MongoDB, each with the scripts that reproduce it, the patch or commits it compares, its results and its raw data.

Every bug here sits in a heuristic: the program measures something (a size, a count, a time), keeps it, and compares it with a bound to choose among options that are all correct, and the choice feeds back into what it measures next. Every one is already public: fixed upstream, or a ticket the vendor holds. Each was reproduced on release builds, the two arms interleaved (the buggy parent and the fix; for MongoDB, two arrival orders of the same queries), and each result reports the latency or throughput, the CPU and the peak memory.

20 bugs:

| # | bug | effect | measured | how | upstream |
|---|---|---|---|---|---|
| 1 | [mongodb/SERVER-107471](bugs/systems/mongodb/SERVER-107471/README.md) | latency, strong | server time 1.8x by arrival order alone; the rare query reads 20,000x the documents (wrong cached plan, never replanned) | two arrival orders, released mongod | declined upstream |
| 2 | [mongodb/SERVER-79039](bugs/systems/mongodb/SERVER-79039/README.md) | latency, strong | 48 vs 2 query plannings, 23 vs 0 replans, optimizer CPU 12.3x by arrival order alone | two arrival orders, released mongod | declined upstream |
| 3 | [postgres/omitted-memory-cost](bugs/systems/postgres/omitted-memory-cost/README.md) | latency, strong | latency 23x, server CPU 60x; 262,144 vs 128 hash batches, 1.59 GB vs 7.2 MB private memory | buggy parent vs the fix | fixed upstream in a1b4f289beec |
| 4 | [postgres/tuples-mistaken-for-groups](bugs/systems/postgres/tuples-mistaken-for-groups/README.md) | latency, strong | query time 1.42x, 29.8x spill batches, RSS 1.44x | buggy parent vs the fix | fixed upstream in 9878b643f37 |
| 5 | [redis/ignores-memory-budget](bugs/systems/redis/ignores-memory-budget/README.md) | latency, strong | worst batch latency 56.6 vs 2.0 ms, server CPU +18%, peak RSS +8.8% | buggy parent vs the fix | fixed upstream in 75f9dec64455 |
| 6 | [rocksdb/unbounded-search](bugs/systems/rocksdb/unbounded-search/README.md) | latency, strong | throughput 0.066x (15x slower), CPU 15.4x | buggy parent vs the fix | fixed upstream in 88bc91f3c |
| 7 | [rocksdb/size-reset-to-zero](bugs/systems/rocksdb/size-reset-to-zero/README.md) | latency, moderate | scan throughput 188.5 vs 250.8 MB/s (272 vs 204 ms per 100,000-entry scan, 1.33x), system CPU 3.3x | buggy parent vs the fix | fixed upstream in 04b2c16f9 |
| 8 | [rocksdb/useless-repeated-switching](bugs/systems/rocksdb/useless-repeated-switching/README.md) | latency, weak | 283-317 vs 0 write stops, stall time 1.81x, throughput unchanged | buggy parent vs the fix | fixed upstream in 91166012c |
| 9 | [valkey/blind-to-target-overload](bugs/systems/valkey/blind-to-target-overload/README.md) | latency, moderate | p99 latency of 100-insert batches 2.52 vs 0.47 ms (5.4x), worst batch 2.8x, server CPU 2.0x, burst 1.28x; median unchanged | buggy parent vs the fix | fixed upstream in 262b371da0d2 |
| 10 | [memcached/stuck-tail-blockers](bugs/systems/memcached/stuck-tail-blockers/README.md) | availability, strong | every write to the slab class refused (2,000 of 2,000; 20,000 of 20,000) vs 0 and 3 with the fix; latency lower only because refusals are immediate | buggy parent vs the fix | fixed upstream in f2a4e5b491ed |
| 11 | [memcached/zero-stuck-backoff](bugs/systems/memcached/zero-stuck-backoff/README.md) | cpu, strong | idle server CPU 99.86% vs 0.00% of a core | buggy parent vs the fix | fixed upstream in 675d89d784df |
| 12 | [rocksdb/marking-ignores-progress](bugs/systems/rocksdb/marking-ignores-progress/README.md) | cpu, strong | an idle database runs 429 compactions per 30 s (986 MB rewritten, 26.8 s CPU, 89% of a core; MANIFEST 940 B to 53 KB) vs none | buggy parent vs the fix | fixed upstream in f7b791b21 |
| 13 | [rocksdb/marking-ignores-progress-3](bugs/systems/rocksdb/marking-ignores-progress-3/README.md) | cpu, strong | an idle database runs 218 compactions per 30 s (1.38 GB rewritten, 21.2 s CPU, 71% of a core; MANIFEST 881 B to 28 KB) vs none | buggy parent vs the fix | fixed upstream in eca47fb69 |
| 14 | [redis/truncated-wait-time](bugs/systems/redis/truncated-wait-time/README.md) | cpu, small | idle CPU 4.8x (hz 10) and 9.3x (hz 100), at most 1.3% of a core | buggy parent vs the fix | fixed upstream in 175a9e3199f7 |
| 15 | [rocksdb/futile-scheduling](bugs/systems/rocksdb/futile-scheduling/README.md) | cpu, small | 219 / 423 / 2,274 no-op compactions per 20 s (0 / 100 / 1,000 marked column families) vs 0; compaction pool 0.36 s CPU per 20 s and ReleaseSnapshot 2.3x at 1,000; put latency unchanged | buggy parent vs the fix | fixed upstream in 416943bf2 |
| 16 | [valkey/self-reinforcing-sampling-skew](bugs/systems/valkey/self-reinforcing-sampling-skew/README.md) | cpu, weak | CPU 2.2x, but the 95% interval touches 1 | buggy parent vs the fix | fixed upstream in 45d03e616421 |
| 17 | [postgres/uncounted-memory](bugs/systems/postgres/uncounted-memory/README.md) | memory, strong | RSS 5.41x (time 1.14x) | buggy parent vs the fix | fixed upstream in 85adc584e2b |
| 18 | [redis/threshold-blocks-idle-free](bugs/systems/redis/threshold-blocks-idle-free/README.md) | memory, strong | accounted memory 1.98x, RSS 1.07x | buggy parent vs the fix | fixed upstream in 0a9377535b6f |
| 19 | [rocksdb/masked-second-trigger](bugs/systems/rocksdb/masked-second-trigger/README.md) | memory, strong | peak RSS 2,627 vs 364 MB; the fix throttles writes, so the buggy version is faster | buggy parent vs the fix | fixed upstream in 18eeb7b90e45 |
| 20 | [valkey/memory-guard-blocks-shrink](bugs/systems/valkey/memory-guard-blocks-shrink/README.md) | memory, strong | lowering maxmemory keeps 0.7% as many keys, CPU 1.58x | buggy parent vs the fix | fixed upstream in 130ea3973ba9 |

## Set up

Linux with [Nix](https://nixos.org/download) (`nix-shell` supplies each system's build tools), python3, git and flock. MongoDB needs `mongod` and `mongosh` of the version its README names.

```sh
export CLIFF_DATA=~/.cache/cliffhunter-bugs          # clones, builds and run directories go here (the default)
tools/reproduce/setup.sh                       # clones the upstream repositories into $CLIFF_DATA/src
tools/reproduce/build.sh redis 5e3a15ae1b58    # one system at one commit, release build, into $CLIFF_DATA/build
```

Then follow the bug's README ("Run it"). Clone the kit to a short path such as `~/cliffhunter-bugs`: PostgreSQL's socket paths must stay under 107 bytes, and one PostgreSQL run keeps its sockets inside the kit.

## Layout

- `bugs/systems/<system>/<bug>/`: the bug's README, `repro/` (scripts and drivers) and, for some, `fix/` (the upstream fix as a diff, for reading: the fixed arm is built from the fix's commit)
- `experiments/reproductions/<system>-<bug>/`: the report and its summaries; `experiments/existing-tools/2026-09-21-jira-repro/`: the MongoDB runs
- `data/experiments/<system>-<bug>/raw/`: raw records of every run
- `tools/reproduce/`: build, measurement and client helpers; `tools/harness/`, `tools/probes/`: MongoDB helpers

## Notes

- Measure on an otherwise idle machine, one campaign at a time: several effects are CPU or latency ratios that other load blurs. A few scripts take `$CLIFF_DATA/locks/machine.lock` with flock for that reason.
- `build.sh` builds with `J=32` jobs; set `J` to your core count.
- Each script uses a fixed port between 15400 and 15499, named in its README.
- Scripts that write to `data/experiments/<system>-<bug>/raw/` replace the recorded data there (git restores it). Scripts that write next to themselves (`repro/data/`, `repro/results/`) often append: clear those before a re-run, as each README says.
- This kit is exported from a larger research repository that is not public. Paths in the reports such as `bugs/tables/queue.tsv`, `data/agents/...` or `docs/...` name files there and are kept as provenance. Machine paths in scripts and logs have been rewritten: `$CLIFF_DATA` stands for the data root.

No license has been chosen yet.

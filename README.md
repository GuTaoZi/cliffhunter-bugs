# cliffhunter-bugs

Reproduced performance bugs that show in latency in Redis, Valkey, PostgreSQL, RocksDB and MongoDB, each with the scripts that reproduce it, the patch or commits it compares, its results and its raw data. Bugs whose cost is only CPU, memory or availability are on the `archive/non-latency` branch.

Every bug here sits in a heuristic: the program measures something (a size, a count, a time), keeps it, and compares it with a bound to choose among options that are all correct, and the choice feeds back into what it measures next. Every one is already public: fixed upstream, a ticket the vendor holds, or a documented server parameter. Each was reproduced on release builds, the two arms interleaved (the buggy parent and the fix; for MongoDB, two arrival orders of the same queries, or the two sides of a bound), and each result reports the latency or throughput, the CPU and the peak memory.

The six MongoDB bugs are measured side by side, with where their time goes and where a timer belongs, in [`docs/mongodb-latency-bugs.md`](docs/mongodb-latency-bugs.md).

13 bugs:

| # | bug | effect | measured | how | upstream |
|---|---|---|---|---|---|
| 1 | [mongodb/SERVER-107471](bugs/systems/mongodb/SERVER-107471/README.md) | latency, strong | rare queries p50/p99 22.6/38.3 vs 1.9/2.4 ms, server CPU 488.7 vs 294.8 ms per run, peak 2,717.1 vs 2,717.2 MB; the rare query reads 20,000x the documents, by arrival order alone | two arrival orders, released mongod | declined upstream |
| 2 | [mongodb/SERVER-79039](bugs/systems/mongodb/SERVER-79039/README.md) | latency, strong | expensive queries p50/p99 68.1/133.5 vs 28.8/78.6 ms, server CPU 1,767.2 vs 819.0 ms per run, peak 3,447.5 vs 3,420.7 MB; 23 vs 0 replans, by arrival order alone | two arrival orders, released mongod | declined upstream |
| 3 | [mongodb/explode-for-sort](bugs/systems/mongodb/explode-for-sort/README.md) | latency, strong | 4.61 to 359.51 ms (78x) and 4,589x the keys from 200 to 201 $in values; on our build of master, server CPU 0.00 to 2.17 s per 5 queries, peak 471.4 MB | either side of a bound, released mongod | fixed upstream in 2014 by raising the cap from 50 to 200 (SERVER-14034); the same cliff at 201 |
| 4 | [mongodb/hash-join](bugs/systems/mongodb/hash-join/README.md) | latency, strong | 11.41 to 2,479.86 ms (217x) from 10,000 to 10,001 foreign documents, CPU 19.1 vs 2,758.4 ms per query; the hash table is under 1 MB | either side of a bound, released mongod | a server parameter (internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000), no ticket |
| 5 | [mongodb/works-ratchet](bugs/systems/mongodb/works-ratchet/README.md) | latency, strong | affected queries p50/p99 384.3/392.0 vs 2.6/3.7 ms, server CPU 10,892.7 vs 1,716.0 ms per run, peak 2,382.8 vs 2,382.5 MB; 0 vs 53 replans, by arrival order alone | arrival orders, released mongod | fixed upstream in 4.1.1 (SERVER-32452) and reachable again; reported again as SERVER-77901, closed Won't Fix |
| 6 | [postgres/omitted-memory-cost](bugs/systems/postgres/omitted-memory-cost/README.md) | latency, strong | latency 23x, server CPU 60x; 262,144 vs 128 hash batches, 1.59 GB vs 7.2 MB private memory | buggy parent vs the fix | fixed upstream in a1b4f289beec |
| 7 | [postgres/tuples-mistaken-for-groups](bugs/systems/postgres/tuples-mistaken-for-groups/README.md) | latency, strong | query time 1.42x, 29.8x spill batches, RSS 1.44x | buggy parent vs the fix | fixed upstream in 9878b643f37 |
| 8 | [redis/ignores-memory-budget](bugs/systems/redis/ignores-memory-budget/README.md) | latency, strong | worst batch latency 56.6 vs 2.0 ms, server CPU +18%, peak RSS +8.8% | buggy parent vs the fix | fixed upstream in 75f9dec64455 |
| 9 | [rocksdb/unbounded-search](bugs/systems/rocksdb/unbounded-search/README.md) | latency, strong | throughput 0.066x (15x slower), CPU 15.4x | buggy parent vs the fix | fixed upstream in 88bc91f3c |
| 10 | [mongodb/trial-period](bugs/systems/mongodb/trial-period/README.md) | latency, moderate | median 1,418.7 vs 25.6 ms with the trial size one larger (101 to 102), CPU 1,524.8 vs 85.2 ms per query, peak 2,182.9 vs 2,183.4 MB | a setting one apart, released mongod | closed as a duplicate of SERVER-79400 (fixed 2023), whose tie-breaker does not fire here (SERVER-14423) |
| 11 | [rocksdb/size-reset-to-zero](bugs/systems/rocksdb/size-reset-to-zero/README.md) | latency, moderate | scan throughput 188.5 vs 250.8 MB/s (272 vs 204 ms per 100,000-entry scan, 1.33x), system CPU 3.3x | buggy parent vs the fix | fixed upstream in 04b2c16f9 |
| 12 | [rocksdb/useless-repeated-switching](bugs/systems/rocksdb/useless-repeated-switching/README.md) | latency, weak | 283-317 vs 0 write stops, stall time 1.81x, throughput unchanged | buggy parent vs the fix | fixed upstream in 91166012c |
| 13 | [valkey/blind-to-target-overload](bugs/systems/valkey/blind-to-target-overload/README.md) | latency, moderate | p99 latency of 100-insert batches 2.52 vs 0.47 ms (5.4x), worst batch 2.8x, server CPU 2.0x, burst 1.28x; median unchanged | buggy parent vs the fix | fixed upstream in 262b371da0d2 |

## Set up

Linux, x86-64. The builds take their compiler and libraries either from the host (Ubuntu or Debian packages) or from [Nix](https://nixos.org/download); `tools/reproduce/inenv.sh` uses Nix when `nix-shell` is installed and the host otherwise, and `CLIFF_TOOLCHAIN=host` or `nix` chooses. Clone the kit to a short path such as `~/cliffhunter-bugs`: PostgreSQL's socket paths must stay under 107 bytes, and one PostgreSQL run keeps its sockets inside the kit.

**On Ubuntu or Debian, without Nix** (tested on Ubuntu 24.04, gcc 13):

```sh
tools/reproduce/deps-ubuntu.sh                 # apt packages: compilers, autotools, bison/flex, RocksDB's
                                               # compression libraries, GNU time, strace (uses sudo)
tools/reproduce/deps-ubuntu.sh perf            # optional: perf, for the MongoDB profiles
export CLIFF_DATA=~/.cache/cliffhunter-bugs          # clones, builds and run directories go here (the default)
tools/reproduce/setup.sh                       # clones the upstream repositories into $CLIFF_DATA/src
tools/reproduce/build.sh redis 5e3a15ae1b58    # one system at one commit, release build, into $CLIFF_DATA/build
eval "$(tools/reproduce/get-mongodb.sh)"        # MongoDB only: mongod 8.2.12 and mongosh 2.9.1 on PATH
```

**With Nix** (any distribution; this is how the recorded runs were built, with gcc 15): install Nix, then the same `setup.sh` and `build.sh` lines; `nix-shell` fetches each build's tools. GNU time, strace and flock come from the host.

Then follow the bug's README ("Run it"). A build records the toolchain and compiler it used in `$CLIFF_DATA/build/<system>-<sha>/flags.txt`. Numbers measured with another compiler can differ somewhat from the recorded ones; the effects are ratios between two arms built the same way.

The MongoDB runs start mongod in a systemd user unit (its own cgroup, for its CPU and memory): they need a systemd user session, which a desktop or SSH login has (on a server without one: `loginctl enable-linger`).

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

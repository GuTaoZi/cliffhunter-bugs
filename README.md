# cliffhunter-bugs

Reproduced performance bugs that show in latency in Redis, Valkey, memcached, PostgreSQL, RocksDB and MongoDB, each with the scripts that reproduce it, the patch or commits it compares, its results and its raw data. Bugs whose cost is only CPU, memory or availability are on the `archive/non-latency` branch.

Every bug here sits in a heuristic: the program measures something (a size, a count, a time), keeps it, and compares it with a bound to choose among options that are all correct, and the choice feeds back into what it measures next. Every one is already public: fixed upstream, a ticket the vendor holds, or a documented server parameter. Each was reproduced on release builds, the two arms interleaved (the buggy parent and the fix; for MongoDB, two arrival orders of the same queries, or the two sides of a bound), and each result reports the latency or throughput, the CPU and the peak memory.

The six MongoDB bugs are measured side by side, with where their time goes and where a timer belongs, in [`docs/mongodb-latency-bugs.md`](docs/mongodb-latency-bugs.md).

31 bugs:

| # | bug | effect | measured | how | upstream |
|---|---|---|---|---|---|
| 1 | [memcached/clock-underflow](bugs/systems/memcached/clock-underflow/README.md) | latency, strong | in the first minute every get hit relinks under the global lock: 64-key multigets at 2.56M vs 7.22M keys/s, p50 202 vs 70 us (4 threads); p99 3.6 ms vs 96 us (16 threads); equal after 65 s of uptime; server CPU 1.12-1.74x; peak RSS equal | buggy parent vs the fix | fixed upstream in d7324b0bd108 |
| 2 | [mongodb/SERVER-107471](bugs/systems/mongodb/SERVER-107471/README.md) | latency, strong | rare queries p50/p99 22.6/38.3 vs 1.9/2.4 ms, server CPU 488.7 vs 294.8 ms per run, peak 2,717.1 vs 2,717.2 MB; the rare query reads 20,000x the documents, by arrival order alone | two arrival orders, released mongod | declined upstream |
| 3 | [mongodb/SERVER-18777](bugs/systems/mongodb/SERVER-18777/README.md) | latency, strong | a rooted $or's cached branch plan serves the other parameter class: 143 vs 1-2 ms per query, never replanned; server CPU 10.3 vs 0.16 s per pass, memory equal | buggy parent vs the fix | open upstream (SERVER-18777, Backlog since 2015) |
| 4 | [mongodb/SERVER-44991](bugs/systems/mongodb/SERVER-44991/README.md) | latency, strong | a checkpoint of prefix-compressed pages read back from disk takes 653 vs 375 ms on tmpfs (1.74x), updates that evict in a 64 MB cache reach 0.60x the throughput with 1.66x the p99; on disk the checkpoint's I/O hides it (CPU 1.37x, update tail 1.24-1.36x); peak RSS equal | buggy parent vs the fix | fixed upstream in WiredTiger 99636a29c679 (WT-5319, 2019-12-14) |
| 5 | [mongodb/SERVER-56274](bugs/systems/mongodb/SERVER-56274/README.md) | latency, strong | an index seek past 1,000,000 entries invisible to a snapshot takes 1,359 ms on 7.0.45 (every entry walked forwards and back) vs 0.19 ms on 8.2.12; server CPU 1,368 vs 0.33 ms per seek; a control both must walk 1.09x; peak RSS equal | buggy parent vs the fix | fixed by bounded cursors, SERVER-65528 to SERVER-88411 (6.2 to 8.1) |
| 6 | [mongodb/SERVER-79039](bugs/systems/mongodb/SERVER-79039/README.md) | latency, strong | expensive queries p50/p99 68.1/133.5 vs 28.8/78.6 ms, server CPU 1,767.2 vs 819.0 ms per run, peak 3,447.5 vs 3,420.7 MB; 23 vs 0 replans, by arrival order alone | two arrival orders, released mongod | declined upstream |
| 7 | [mongodb/explode-for-sort](bugs/systems/mongodb/explode-for-sort/README.md) | latency, strong | 4.61 to 359.51 ms (78x) and 4,589x the keys from 200 to 201 $in values; on our build of master, server CPU 0.00 to 2.17 s per 5 queries, peak 471.4 MB | either side of a bound, released mongod | fixed upstream in 2014 by raising the cap from 50 to 200 (SERVER-14034); the same cliff at 201 |
| 8 | [mongodb/hash-join](bugs/systems/mongodb/hash-join/README.md) | latency, strong | 11.41 to 2,479.86 ms (217x) from 10,000 to 10,001 foreign documents, CPU 19.1 vs 2,758.4 ms per query; the hash table is under 1 MB | either side of a bound, released mongod | a server parameter (internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000), no ticket |
| 9 | [mongodb/works-ratchet](bugs/systems/mongodb/works-ratchet/README.md) | latency, strong | affected queries p50/p99 384.3/392.0 vs 2.6/3.7 ms, server CPU 10,892.7 vs 1,716.0 ms per run, peak 2,382.8 vs 2,382.5 MB; 0 vs 53 replans, by arrival order alone | arrival orders, released mongod | fixed upstream in 4.1.1 (SERVER-32452) and reachable again; reported again as SERVER-77901, closed Won't Fix |
| 10 | [postgres/decay-outruns-growth](bugs/systems/postgres/decay-outruns-growth/README.md) | latency, strong | a scan with one uncached block in every 64 takes 23.0 vs 11.2 s (2.05x; 24.3 vs 9.9 s at effective_io_concurrency 64), all-cold control equal; server CPU 1.9x, peak RSS equal | buggy parent vs the fix | fixed upstream in 6e36930f9aaf |
| 11 | [postgres/omitted-memory-cost](bugs/systems/postgres/omitted-memory-cost/README.md) | latency, strong | latency 23x, server CPU 60x; 262,144 vs 128 hash batches, 1.59 GB vs 7.2 MB private memory | buggy parent vs the fix | fixed upstream in a1b4f289beec |
| 12 | [postgres/tuples-mistaken-for-groups](bugs/systems/postgres/tuples-mistaken-for-groups/README.md) | latency, strong | query time 1.42x, 29.8x spill batches, RSS 1.44x | buggy parent vs the fix | fixed upstream in 9878b643f37 |
| 13 | [redis/budget-checked-too-coarsely](bugs/systems/redis/budget-checked-too-coarsely/README.md) | latency, strong | one defrag cycle blocks 175-184 ms against a 2.5 ms budget; worst PING 177.8 vs 4.5 ms; the fix takes 2.1x the CPU, peak RSS equal | buggy parent vs the fix | fixed upstream in 485425cec76e |
| 14 | [redis/empty-sample-means-repeat](bugs/systems/redis/empty-sample-means-repeat/README.md) | latency, strong | with a fork child alive and the expires dict emptied, active expire spins its budget: PING corrected p99 25.3 vs 0.15 ms, 238 vs 0 PINGs over 10 ms in 30 s, main-thread CPU 16.5 vs 0.53 s; control without the child flat; peak RSS equal | buggy parent vs the fix | fixed upstream in f20774eced7e |
| 15 | [redis/ignores-memory-budget](bugs/systems/redis/ignores-memory-budget/README.md) | latency, strong | worst batch latency 56.6 vs 2.0 ms, server CPU +18%, peak RSS +8.8% | buggy parent vs the fix | fixed upstream in 75f9dec64455 |
| 16 | [redis/no-yield-feedback](bugs/systems/redis/no-yield-feedback/README.md) | latency, strong | defrag keeps 50% effort on fragmentation it cannot move: steady PING corrected p99 48.7 vs 2.1 ms, main-thread CPU 31% vs 4% of a core; peak RSS equal | buggy parent vs the fix | fixed upstream in f86575f210a9 |
| 17 | [redis/unknown-type-costed-1](bugs/systems/redis/unknown-type-costed-1/README.md) | latency, strong | UNLINK of a 3,000,000-entry stream blocks 168 vs 0.22 ms; worst PING 167 vs 3.4 ms; DEL control equal in both; peak RSS equal | buggy parent vs the fix | fixed upstream in 5b0a06af4899 |
| 18 | [redis/wrong-scaling-formula](bugs/systems/redis/wrong-scaling-formula/README.md) | latency, strong | expiring 2,000,000 keys, fast expire cycles of 250 vs 25 ms; worst PING 277.5 vs 28.5 ms; the fix's p99 1.5 vs 0.09 ms and CPU 1.65x | buggy parent vs the fix | fixed upstream in 2ab51a644d3d |
| 19 | [rocksdb/age-clamped-to-zero](bugs/systems/rocksdb/age-clamped-to-zero/README.md) | latency, strong | each stats dump rescans the block cache about 133 times under the DB mutex: longest write 6.44 s vs 10 ms, overwrite 128k vs 737k writes/s; CPU 2.4x, peak RSS equal | buggy parent vs the fix | fixed upstream in 2f93a3b80912 |
| 20 | [rocksdb/stall-cannot-help](bugs/systems/rocksdb/stall-cannot-help/README.md) | latency, strong | 80,000 writes with auto compaction off take 41.3 vs 0.13 s, p99 write 1,196 vs 1.8 us; at the stop trigger the parent never finishes; peak RSS equal | buggy parent vs the fix | fixed upstream in ee027fc19f4a |
| 21 | [rocksdb/unbounded-search](bugs/systems/rocksdb/unbounded-search/README.md) | latency, strong | throughput 0.066x (15x slower), CPU 15.4x | buggy parent vs the fix | fixed upstream in 88bc91f3c |
| 22 | [rocksdb/waiting-on-nothing](bugs/systems/rocksdb/waiting-on-nothing/README.md) | latency, strong | a delayed write sleeps 1.001 s after a 23 ms flush ended the slowdown; p99 write 1.001 s vs 23 ms, total stall 24.0 vs 0.66 s; peak RSS equal | buggy parent vs the fix | fixed upstream in d52f334cbd4b |
| 23 | [valkey/banked-negative-overage](bugs/systems/valkey/banked-negative-overage/README.md) | latency, strong | each defrag restart past 30 empty stages gives one 13.4 ms main-thread stall vs at most 2.9 ms: 10 vs 0 PINGs over 10 ms; CPU 1.13x; peak RSS equal | buggy parent vs the fix | fixed upstream in 0c8ad5cd3412 |
| 24 | [valkey/coarse-time-check-2](bugs/systems/valkey/coarse-time-check-2/README.md) | latency, strong | 10,000,000 fields expiring together: PING raw p99 26.6 vs 2.9 ms, corrected p99 976 vs 35 ms, expire cycles 32 vs 25.5 ms; the fix drains in 7.4 vs 1.7 s with 3x the CPU; peak RSS equal | buggy parent vs the fix | fixed upstream in 3213f48fd694 |
| 25 | [valkey/forced-synchronous-catch-up](bugs/systems/valkey/forced-synchronous-catch-up/README.md) | latency, strong | after a set's shrink, the insert that asks for a resize finishes the whole rehash: worst SADD 63.4 vs 18.9 ms at the predicted insert; median, CPU and peak RSS about equal | buggy parent vs the fix | fixed upstream in aefed3d363d1 |
| 26 | [valkey/key-count-only-bound](bugs/systems/valkey/key-count-only-bound/README.md) | latency, strong | tracking-table eviction blocks up to 320 vs 7.3 ms (worst PING), 3.8 vs 0 stalls over 100 ms; the fix takes 1.8x the CPU | buggy parent vs the fix | fixed upstream in 9b270b6d8b1a |
| 27 | [mongodb/trial-period](bugs/systems/mongodb/trial-period/README.md) | latency, moderate | median 1,418.7 vs 25.6 ms with the trial size one larger (101 to 102), CPU 1,524.8 vs 85.2 ms per query, peak 2,182.9 vs 2,183.4 MB | a setting one apart, released mongod | closed as a duplicate of SERVER-79400 (fixed 2023), whose tie-breaker does not fire here (SERVER-14423) |
| 28 | [postgres/gave-up-advising-early](bugs/systems/postgres/gave-up-advising-early/README.md) | latency, moderate | a cold VACUUM over 48-block runs takes 15.2 vs 10.5 s (1.44x) with the same bytes read; with advice off both 10.4 s; over 16-block runs the fix is 1.5x slower (5.84 vs 3.88 s); CPU and peak RSS equal | buggy parent vs the fix | fixed upstream in 7ea8cd15661e |
| 29 | [rocksdb/size-reset-to-zero](bugs/systems/rocksdb/size-reset-to-zero/README.md) | latency, moderate | scan throughput 188.5 vs 250.8 MB/s (272 vs 204 ms per 100,000-entry scan, 1.33x), system CPU 3.3x | buggy parent vs the fix | fixed upstream in 04b2c16f9 |
| 30 | [rocksdb/useless-repeated-switching](bugs/systems/rocksdb/useless-repeated-switching/README.md) | latency, weak | 283-317 vs 0 write stops, stall time 1.81x, throughput unchanged | buggy parent vs the fix | fixed upstream in 91166012c |
| 31 | [valkey/blind-to-target-overload](bugs/systems/valkey/blind-to-target-overload/README.md) | latency, moderate | p99 latency of 100-insert batches 2.52 vs 0.47 ms (5.4x), worst batch 2.8x, server CPU 2.0x, burst 1.28x; median unchanged | buggy parent vs the fix | fixed upstream in 262b371da0d2 |

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

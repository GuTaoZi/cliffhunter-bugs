# redis/ignores-memory-budget

Reproduced, a fixed bug (parent vs fix): the keyspace dict expands past maxmemory at 2^n keys; worst batch latency 56.6 vs 2.0 ms, server CPU +18%, peak RSS +8.8%, 10% fewer keys kept; under noeviction 1 of 300,000 writes accepted (parent) vs 115,937 (fix)

- **Upstream:** fixed upstream in 75f9dec64455
- **Effect:** latency, strong: worst batch latency 56.6 vs 2.0 ms, server CPU +18%, peak RSS +8.8%
- **Experiment:** P16, report: [experiments/reproductions/redis-ignores-memory-budget/README.md](../../../../experiments/reproductions/redis-ignores-memory-budget/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); about 2 GB of free RAM

**Build:**

```sh
tools/reproduce/build.sh redis 2f41a3856845
tools/reproduce/build.sh redis 75f9dec64455
```

**Run:**

```sh
RP=bugs/systems/redis/ignores-memory-budget/repro
sh $RP/series.sh A-lru-4M allkeys-lru 4194304 8388608 1000000 5 20 > $RP/series-A.log
sh $RP/series.sh B-noevict-4M noeviction 4194304 8388608 300000 5 10 > $RP/series-B.log
sh $RP/series.sh C-lru-16M allkeys-lru 16777216 33554432 3000000 3 60 > $RP/series-C.log
python3 $RP/summarize.py $RP/data/A-lru-4M $RP/data/B-noevict-4M $RP/data/C-lru-16M > $RP/results.md
```

**Writes:** repro/data/<series>/ (one result, insert record and server log per run), repro/results.md

**Minutes:** about 10

**Notes:** series.sh takes NAME POLICY N MARGIN K REPS SETTLE. Port 15430: run the three series one after another.

## The report

Copied from [`experiments/reproductions/redis-ignores-memory-budget/README.md`](../../../../experiments/reproductions/redis-ignores-memory-budget/README.md).

### P16 redis-ignores-memory-budget — the keyspace dict expands past maxmemory

Queue rank 2 of `bugs/tables/queue.tsv` (severity 5, relevance 4.5, two raters). Reproduced on 2026-10-22 by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`); its report follows, as returned. Code: `bugs/systems/redis/ignores-memory-budget/repro/`; raw data: `data/experiments/redis-ignores-memory-budget/raw/`.

Runs took place from 21:34 to 21:54 EDT on 2026-10-22.

#### Verdict
**Confirmed.** At the fix's parent, the first insert past a power-of-two key count allocates a bucket array twice the size of the old one, even though maxmemory is close. Used memory then goes 55 MiB (4M keys) or 223 MiB (16M keys) over the limit. The server spends about 0.8 s (4M) or 4.3 s (16M) evicting keys in 55 ms stalls, and it ends with 10% fewer keys. Under noeviction, the parent rejects every write after the one that caused the expansion. The fix does none of this. Every difference is many standard deviations wide.

#### Arms
| arm | commit | build dir | flags (checked in build.log) |
|---|---|---|---|
| parent (buggy) | 2f41a3856845 | $CLIFF_DATA/build/redis-2f41a3856845 | gcc 15.3.0, `-O2 -g -ggdb -std=gnu11 -fcommon`, MALLOC=jemalloc |
| fix | 75f9dec64455 | $CLIFF_DATA/build/redis-75f9dec64455 | same |

Both were built with `tools/reproduce/build.sh redis COMMIT` under the machine lock (`build.out`).

#### Workload
`run.py` runs one repetition of one arm. `series.sh` interleaves the arms and alternates which one runs first in each repetition.
1. Start redis-server on 127.0.0.1:15430 with `--maxmemory 0`, the given policy, no save and no AOF.
2. Run `DEBUG POPULATE N` with N a power of two. Its `dictExpand(c->db->dict,keys)` (src/debug.c:606@2f41a3856845) gives db0 exactly N buckets at load factor 1.0, so the next new key reaches the expansion check.
3. Wait 1 s, set maxmemory to used_memory plus MARGIN, then run `CONFIG RESETSTAT`.
4. Measured phase: `tools/reproduce/measure.py --pid <server>` runs `insert.py`.
   - `insert.py` sends K `SET new:i value:i` commands, pipelined in batches of 100, timing each batch and counting OOM replies.
   - A second connection samples INFO memory/stats and MEMORY STATS every 50 ms, for used_memory, evicted_keys, the key count and db0's bucket count.
   - Afterwards it waits until used_memory is within maxmemory and the dict has stopped rehashing, or until SETTLE seconds pass.
5. Record DBSIZE, evicted_keys and the `DEBUG HTSTATS 0` table sizes, then stop the server.

| config | policy | N | MARGIN | K | reps per arm |
|---|---|---|---|---|---|
| A | allkeys-lru | 2^22 = 4,194,304 (next array 64 MiB) | 8 MiB | 1,000,000 | 5 |
| B | noeviction | 2^22 | 8 MiB | 300,000 | 5 |
| C | allkeys-lru | 2^24 = 16,777,216 (next array 256 MiB) | 32 MiB | 3,000,000 | 3 |

Commands:
```
flock .../locks/machine.lock .../series.sh A-lru-4M allkeys-lru 4194304 8388608 1000000 5 20
flock .../locks/machine.lock .../series.sh B-noevict-4M noeviction 4194304 8388608 300000 5 10
flock .../locks/machine.lock .../series.sh C-lru-16M allkeys-lru 16777216 33554432 3000000 3 60
python3 summarize.py data/A-lru-4M data/B-noevict-4M data/C-lru-16M > results.md
```

#### Results
Values are mean ± sd. Latency is per batch of 100 SETs as the client sees it. CPU and peak RSS are the server's, over the measured window.

**A: allkeys-lru, 4M keys, maxmemory = used + 8 MiB, 1M SETs (5 reps)**
| metric | parent | fix | difference |
|---|---|---|---|
| server CPU (s) | 5.02 ± 0.04 | 4.26 ± 0.02 | +0.76 s (+18%) |
| server peak RSS (MB) | 426.0 ± 1.9 | 391.5 ± 0.1 | +34.5 MB (+8.8%) |
| batch latency max (ms) | 56.6 ± 0.5 | 2.03 ± 0.23 | 28x |
| batches over 10 ms | 15 | 0 | |
| batch latency p99 (ms) | 1.51 ± 0.20 | 1.25 ± 0.02 | |
| batch latency p50 (ms) | 0.98 ± 0.16 | 0.93 ± 0.18 | within noise |
| insert phase wall (s) | 11.4 ± 1.3 | 9.8 ± 0.8 | about 1.2 sd: not claimed |
| peak used_memory over maxmemory (MiB) | 54.91 ± 0.07 | 0.02 | |
| time until back within budget (s) | 0.83 | n/a | |
| evicted_keys | 1,248,485 ± 25 | 810,084 ± 14 | +438,401 (+54%) |
| lowest key count during run | 3,839,767 | 4,194,304 (never below start) | parent loses 8.5% of keys in under 1 s |
| final key count | 3,945,819 ± 25 | 4,384,220 ± 14 | parent keeps 10.0% fewer |
| db0 buckets before -> after | 4,194,304 -> 8,388,608 | unchanged (load factor 1.045) | |

**C: allkeys-lru, 16M keys, maxmemory = used + 32 MiB, 3M SETs (3 reps)**
| metric | parent | fix | difference |
|---|---|---|---|
| server CPU (s) | 17.4 ± 0.12 | 13.7 ± 0.04 | +3.8 s (+27%) |
| server peak RSS (MB) | 1687.7 ± 0.4 | 1479.8 ± 0.1 | +208 MB (+14%) |
| batch latency max (ms) | 57.7 ± 0.3 | 6.5 ± 0.3 | |
| batches over 10 ms | 76 ± 1 | 0 | |
| batch latency p99 / p50 (ms) | 1.68 / 1.07 | 1.28 / 1.10 | |
| insert phase wall (s) | 37.5 ± 0.7 | 31.0 ± 0.5 | +21% |
| peak used_memory over maxmemory (MiB) | 223.07 | 0.02 | |
| time until back within budget (s) | 4.26 | n/a | |
| evicted_keys | 4,187,535 ± 63 | 2,491,302 ± 16 | +1,696,233 (+68%) |
| lowest key count during run | 15,358,536 | 16,777,216 | parent loses 8.5% |
| final key count | 15,589,681 | 17,285,914 | parent keeps 9.8% fewer |
| db0 buckets before -> after | 16.8M -> 33.6M | unchanged (load factor 1.030) | |

**B: noeviction, 4M keys, maxmemory = used + 8 MiB, 300K SETs (5 reps): rejected writes**
| metric | parent | fix |
|---|---|---|
| SETs accepted / rejected with OOM | 1 / 299,999 (every rep) | 115,937 / 184,063 (every rep) |
| peak used_memory over maxmemory (MiB) | 56.08 | 0.04 |
| server peak RSS (MB) | 370.5 ± 0.3 | 365.0 ± 0.1 |
| batch latency max (ms) | 2.28 | 0.80 |
| server CPU (s) / measured window (s) | 0.536 / 11.1 | 0.436 / 1.9 |
| db0 bucket arrays at end | 4,194,304 + 8,388,608 (still rehashing) | 4,194,304 |

CPU in B is not a like-for-like comparison. The parent never gets back under maxmemory, so its settle wait runs the full 10 s while the cron rehashes.

#### Mechanism
Parent (2f41a3856845):
- **The load factor alone decides.** `_dictExpandIfNeeded` (src/dict.c:955-971@2f41a3856845) runs on every insert, through dict.c:1003. When `used >= size` it calls `dictExpand(d, d->ht[0].used*2)` (dict.c:967-971). It does not check memory.
- **The whole new array is counted at once.** `dictExpand` calls `zcalloc(realsize*sizeof(dictEntry*))` (dict.c:163): 64 MiB in A, 256 MiB in C. used_memory takes all of it on the first SET; the traces show 8 MiB under the limit becoming 55 or 223 MiB over.
- **Eviction runs in 500 µs slices per command.** `processCommand` calls `performEvictions()` before each command (src/server.c:3760@2f41a3856845). Each call evicts for up to `evictionTimeLimitUs()`, which is 50 µs x tenacity 10 = 500 µs (src/evict.c:461-463; default tenacity at src/config.c:2381). It then hands off to `evictionTimeProc` (evict.c:660-664). So a batch of 100 SETs takes about 55 ms, which gives the 15 (A) and 76 (C) slow batches until the overshoot has been evicted.
- **Fewer keys for good.** After rehashing (server.c:1486-1489 cron, old table freed at dict.c:222), the parent holds an array twice as large: 64 MiB against 32 MiB in A, 256 MiB against 128 MiB in C. The final key-count gap equals the eviction gap exactly (438,401 and 1,696,233 keys). Dividing the extra 32 or 128 MiB by those gaps gives 76.5 and 79.1 bytes per key, which is this dataset's per-key size. This is the commit's "redis will keep less keys".
- **noeviction.** `performEvictions` returns EVICT_FAIL, so every denyoom command is rejected with OOM (server.c:3760-3778).

Fix (75f9dec64455):
- The condition adds `dictTypeExpandAllowed(d)` (src/dict.c:976-982@75f9dec64455), which passes `_dictNextPower(used+1)*8` and `used/size` to the type's callback (dict.c:957-962).
- For dbDictType and dbExpiresDictType (server.c:1368, 1390), the callback is `dictExpandAllowed` (server.c:1307-1309). While the load factor is at most 1.618 (server.h:164), it refuses whenever `overMaxmemoryAfterAlloc` (evict.c:418-427) says the new array would exceed maxmemory.
- The fix arm's load factor stayed at 1.03-1.05. It never expanded, and the longer chains had no visible cost: p50 was unchanged.
- The fix's other change, from `used*2` to `used+1`, gives the same target size here, so it plays no part.

#### What did not work, and caveats
- **The first smoke test failed** (N=65,536, 64 KiB margin, in `smoke/`). Neither arm expanded and the results were identical. The two new client connections (client structs and query buffers) used more than 64 KiB, so eviction started before the first SET and the key count never reached 2^16. The fix for this was a margin far above client overhead but below the next array: 8 MiB and 32 MiB.
- **HTSTATS was too costly to sample.** `DEBUG HTSTATS` walks every bucket, which is too heavy for the 50 ms trace. The trace derives the bucket count from MEMORY STATS (src/object.c:1053-1055@2f41a3856845) instead, and HTSTATS runs only before and after the measured phase.
- **The trigger is set up deliberately.** DEBUG POPULATE puts the dict at load factor 1.0, so the first new key crosses 2^n. In production this happens whenever growth reaches 2^n keys with used_memory within one array size of maxmemory.
- **Some numbers are noisy.** Client-side numbers (p50, and insert wall time in A) are bimodal in both arms; the machine is shared (load average 1-7) and there is one Python client. Server CPU, RSS and the eviction and key counters are tight (sd under 1%).
- All servers were stopped, and nothing listens on 15430-15439. The repository was not modified.

#### Files
Scripts (`build_arms.sh`, `run.py`, `insert.py`, `series.sh`, `summarize.py`) are in the bug's `repro/` directory; logs (`build.out`, `series-A.log`, `series-B.log`, `series-C.log`), the summary tables (`results.md`), the raw data (`data/A-lru-4M/`, `data/B-noevict-4M/`, `data/C-lru-16M/`: per run `*.result.json`, `*.insert.json` with the trace and per-batch latency series, `*.server.log`) and the smoke tests (`smoke/`) are in `data/experiments/redis-ignores-memory-budget/raw/`.

## Files

- [`repro/build_arms.sh`](repro/build_arms.sh)
- [`repro/insert.py`](repro/insert.py)
- [`repro/run.py`](repro/run.py)
- [`repro/series.sh`](repro/series.sh)
- [`repro/summarize.py`](repro/summarize.py)

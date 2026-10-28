# redis/wrong-scaling-formula

Reproduced, a fixed bug (parent vs fix): removing 2,000,000 expired keys, the fast expire cycle runs 250 ms instead of 1 ms; worst PING 277.5 vs 28.5 ms (9.8x), 5 vs 0 stalls over 100 ms per run; the fix's p99 is 1.5 vs 0.09 ms and its CPU 2.6 vs 1.6 s; peak RSS equal

- **Upstream:** fixed upstream in 2ab51a644d3d
- **Effect:** latency, strong: expiring 2,000,000 keys, fast expire cycles of 250 vs 25 ms; worst PING 277.5 vs 28.5 ms; the fix's p99 1.5 vs 0.09 ms and CPU 1.65x
- **Experiment:** P35, report: [experiments/reproductions/redis-wrong-scaling-formula/README.md](../../../../experiments/reproductions/redis-wrong-scaling-formula/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 2 free cores

**Build:**

```sh
python3 bugs/systems/redis/wrong-scaling-formula/repro/run.py build
```

**Run:**

```sh
python3 bugs/systems/redis/wrong-scaling-formula/repro/run.py measure 5
python3 bugs/systems/redis/wrong-scaling-formula/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/probe-*.json, repro/logs/, repro/results.md

**Minutes:** about 2

**Notes:** run.py build builds parent 1ccc270a2cb3 and fix 2ab51a644d3d. report averages every row of data/runs.jsonl: delete it before a re-run. Port 15441; cores 2 and 4.

## The report

Copied from [`experiments/reproductions/redis-wrong-scaling-formula/README.md`](../../../../experiments/reproductions/redis-wrong-scaling-formula/README.md).

### P35 redis-wrong-scaling-formula — the fast expire cycle gets 250 ms instead of 1 ms

Queue rank 57 of `bugs/tables/queue.tsv` (severity 4, relevance 4, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/redis/wrong-scaling-formula/repro/`; raw data: `data/experiments/redis-wrong-scaling-formula/raw/`.

**The bug.** Redis's fast expire cycle (`src/expire.c` at 1ccc270a2cb3, lines 127-136) gets a time budget of `ACTIVE_EXPIRE_CYCLE_FAST_DURATION * ACTIVE_EXPIRE_CYCLE_FAST_DURATION/4*effort` microseconds: 1000 × 1000 / 4 × 1 = 250,000 µs at the default `active-expire-effort` 1, where 1,000 µs was meant. The fast cycle runs on the main thread from `beforeSleep` (`server.c:2097-2098`) whenever the previous cycle hit its time limit, at most every 500 ms (`expire.c:163`), so a backlog of expired keys blocks every client for up to 250 ms at a time. Fixed upstream in 2ab51a644d3d (2019-11-18): `effort-1`, and `+` instead of `*`, giving 1000 + 250 × (effort − 1) = 1,000 µs.

**Arms.** Parent 1ccc270a2cb3 against the fix 2ab51a644d3d, release builds (`tools/reproduce/build.sh`: GCC 15.3, `-O2`, jemalloc), fresh server per run (`--hz 10 --latency-monitor-threshold 10`, plus `--save "" --appendonly no`), port 15441, the server pinned to one core and the probe to another. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload.** With active expiry off (`DEBUG SET-ACTIVE-EXPIRE 0`), `DEBUG POPULATE 2000000`, then `PEXPIRE key 1` on every key (Lua batches of 200,000) and a 0.5 s wait, so all 2,000,000 keys are logically expired and none is removed yet. Measured: a PING every 1 ms on its own connection and core (`tools/reproduce/pingprobe.py`: raw round trip, and latency from the scheduled send time, which counts a stall's whole length rather than one sample), started 1 s before `DEBUG SET-ACTIVE-EXPIRE 1`; the window ends 1 s after `DBSIZE` reaches 0. Server CPU (all threads) and main-thread CPU from `/proc`, peak RSS (VmHWM reset at the start of the window), and the server's own `LATENCY HISTORY expire-cycle`.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| while 2,000,000 expired keys are removed | parent | fix | parent / fix |
|---|---|---|---|
| worst PING round trip | 277.5 ms (sd 0.07) | 28.5 ms (sd 0.13) | 9.8 |
| p99 from the scheduled send | 269.9 ms | 25.4 ms | 10.6 |
| PINGs over 100 ms per run | 5 | 0 | |
| longest expire cycle (`LATENCY HISTORY`) | 250 ms | 25 ms | 10.0 |
| median PING | 0.044 ms | 0.044 ms | 1.0 |
| p99 PING round trip | 0.090 ms | 1.50 ms | 0.06 |
| time to remove all keys | 3.9 s | 5.5 s | 0.71 |
| server CPU | 1.59 s (sd 0.04) | 2.64 s (sd 0.13) | 0.60 |
| peak RSS | 247.1 MB | 246.7 MB | 1.0 |

The parent's history shows the mechanism directly: each run has four 240-250 ms expire cycles (`[27, 250, 250, 240, 27]` in run 1) and the time cap was reached 14 times; the fix's cycles are all the slow cycle's 25 ms (the slow cycle, 25% of a 100 ms tick, is unchanged by the fix and bounds both arms' worst case) and the cap was reached 1,262 times, as 1 ms fast cycles. The fix is not free: its many short fast cycles raise the PING p99 from 0.09 to 1.5 ms, take 40% longer to remove the keys and use 66% more CPU. The bug is in latency: one client waits up to a quarter of a second, five times per run.

## Files

- [`repro/run.py`](repro/run.py)

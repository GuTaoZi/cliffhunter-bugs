# valkey/key-count-only-bound

Reproduced, a fixed bug (parent vs fix): lowering tracking-table-max-keys under 10,000 keys tracked by 300 RESP3 clients blocks the server in growing eviction calls; worst PING 320 vs 7.3 ms (44x), p99.9 83 vs 4.2 ms, 3.8 vs 0 stalls over 100 ms; the fix drains in 2.7 vs 1.1 s with 1.8x the CPU and a 2.2 ms p99

- **Upstream:** fixed upstream in 9b270b6d8b1a
- **Effect:** latency, strong: tracking-table eviction blocks up to 320 vs 7.3 ms (worst PING), 3.8 vs 0 stalls over 100 ms; the fix takes 1.8x the CPU
- **Experiment:** P33, report: [experiments/reproductions/valkey-key-count-only-bound/README.md](../../../../experiments/reproductions/valkey-key-count-only-bound/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 2 free cores; 300 client sockets

**Build:**

```sh
python3 bugs/systems/valkey/key-count-only-bound/repro/run.py build
```

**Run:**

```sh
python3 bugs/systems/valkey/key-count-only-bound/repro/run.py measure 5
python3 bugs/systems/valkey/key-count-only-bound/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/probe-*.json, repro/logs/, repro/results.md

**Minutes:** about 1

**Notes:** run.py build builds parent 3293091659be and fix 9b270b6d8b1a. Latency from the scheduled send time (cor_*) grows in both arms here and does not measure stall length; read the raw round trips. report averages every row of data/runs.jsonl: delete it before a re-run. Port 15444; cores 2 and 4.

## The report

Copied from [`experiments/reproductions/valkey-key-count-only-bound/README.md`](../../../../experiments/reproductions/valkey-key-count-only-bound/README.md).

### P33 valkey-key-count-only-bound — tracking-table eviction bounded by a growing key count, not time

Queue rank 39 of `bugs/tables/queue.tsv` (severity 3.5, relevance 5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/valkey/key-count-only-bound/repro/`; raw data: `data/experiments/valkey-key-count-only-bound/raw/`.

**The bug.** When Valkey's client-side-caching tracking table holds more than `tracking-table-max-keys` keys, `trackingLimitUsedSlots` (`src/tracking.c` at 3293091659be, lines 519-555) evicts `effort = 100 * (timeout_counter + 1)` keys per call (531), and the counter grows on every call that does not reach the limit (554). Evicting a key sends an invalidation push to every client tracking it (373-424), so a call costs keys × clients with no time bound, and it runs before every command (`server.c:4894`) and in `serverCron` (`server.c:1790`). Fixed upstream in 9b270b6d8b1a (2026-09-30): the loop also stops after `TRACKING_EVICTION_TIME_LIMIT_US` (500 µs).

**Arms.** Parent 3293091659be against the fix 9b270b6d8b1a, release builds (`tools/reproduce/build.sh`: GCC 15.3, `-O3`, Valkey's default, jemalloc), fresh server per run (`--enable-debug-command yes --maxclients 2000`), port 15444, server and probe pinned to different cores. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload.** `DEBUG POPULATE 10000`; 300 clients each send `HELLO 3`, `CLIENT TRACKING ON` and an `MGET` of all 10,000 keys (RESP3, because a RESP2 client without redirect gets no push, `tracking.c:307`), so the table holds 10,000 keys with 3,000,000 tracking items; the clients are not read afterwards. Measured: a PING every 1 ms on its own connection and core (`tools/reproduce/pingprobe.py`), and 1 s later `CONFIG SET tracking-table-max-keys 10` from another connection; the window ends 2 s after `tracking_total_keys` is at most 10. Server CPU, main-thread CPU and peak RSS over the window.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| evicting 9,990 keys tracked by 300 clients | parent | fix | parent / fix |
|---|---|---|---|
| worst PING round trip | 319.9 ms (sd 43) | 7.3 ms (sd 0.5) | 44 |
| p99.9 PING round trip | 83.0 ms | 4.2 ms | 20 |
| PINGs over 100 ms per run | 3.8 | 0 | |
| PINGs over 10 ms per run | 7.6 | 0 | |
| time the server did not answer (beyond 1 ms) | 1,059 ms | 142 ms | 7.5 |
| median PING | 0.046 ms | 0.046 ms | 1.0 |
| p99 PING round trip | 0.086 ms | 2.16 ms | 0.04 |
| time until the table is at the limit | 1.10 s | 2.66 s | 0.42 |
| server CPU | 1.13 s | 2.08 s | 0.54 |
| peak RSS | 191.6 MB | 169.4 MB | 1.13 |

The parent drains the table in a few growing calls (keys left: 8,500 at 0.2 s, 5,500 at 0.6 s, 900 at 1.06 s), each blocking every client for up to 320 ms; the fix drains it about 400 keys per 100 ms, never blocking for more than 7.3 ms. The fix's p99 rises (2.2 ms) because every command, the probe's PINGs included, pays its 500 µs eviction slice and the pushes it sends while the table is over the limit, and it uses more CPU. One measure does not separate the arms here: latency from the scheduled send time grows to about 1 s in both (p99.9 1,055 vs 779 ms), because at a PING every 1 ms the fix's per-command cost exceeds the offered rate while the table drains, so that series measures capacity at the probe's rate rather than stall length. The raw round trips, the stall counts and the blocked time are the stall measures. The bug is in latency.

## Files

- [`repro/run.py`](repro/run.py)

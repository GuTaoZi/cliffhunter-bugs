# redis/budget-checked-too-coarsely

Reproduced, a fixed bug (parent vs fix): active defrag of a 500,000-node list runs in one 175-184 ms main-thread cycle against a 2.5 ms budget; worst PING 177.8 vs 4.5 ms (40x), longest defrag cycle 177 vs 3 ms; the fix takes 4x the wall time and 2.1x the CPU for the same work; peak RSS equal

- **Upstream:** fixed upstream in 485425cec76e
- **Effect:** latency, strong: one defrag cycle blocks 175-184 ms against a 2.5 ms budget; worst PING 177.8 vs 4.5 ms; the fix takes 2.1x the CPU, peak RSS equal
- **Experiment:** P30, report: [experiments/reproductions/redis-budget-checked-too-coarsely/README.md](../../../../experiments/reproductions/redis-budget-checked-too-coarsely/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 2 free cores; about 1.4 GB of RAM

**Build:**

```sh
python3 bugs/systems/redis/budget-checked-too-coarsely/repro/run.py build
```

**Run:**

```sh
python3 bugs/systems/redis/budget-checked-too-coarsely/repro/run.py measure 5
python3 bugs/systems/redis/budget-checked-too-coarsely/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/probe-*.json, repro/logs/, repro/results.md

**Minutes:** about 2

**Notes:** run.py build builds parent df45fed050d6 and fix 485425cec76e (bundled jemalloc, needed for active defrag). report averages every row of data/runs.jsonl: delete it before a re-run. Port 15443; the server and the probe are pinned to cores 2 and 4.

## The report

Copied from [`experiments/reproductions/redis-budget-checked-too-coarsely/README.md`](../../../../experiments/reproductions/redis-budget-checked-too-coarsely/README.md).

### P30 redis-budget-checked-too-coarsely — active defrag ignores its time budget inside a large list

Queue rank 33 of `bugs/tables/queue.tsv` (severity 4, relevance 4.5, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/redis/budget-checked-too-coarsely/repro/`; raw data: `data/experiments/redis-budget-checked-too-coarsely/raw/`.

**The bug.** Redis's active defrag (`src/defrag.c` at df45fed050d6) works in cycles with a time budget of `1e6 * active_defrag_running / hz / 100` µs (lines 1071-1073), but checks it only between keys (`defragLaterStep`, 959-975). A list of more than `active-defrag-max-scan-fields` (1,000) quicklist nodes is deferred (`defragLater`, 512-524) and then defragged by `scanLaterList` (443-449), which walks every node in one go (`activeDefragQuickListNodes`, 411-433, no time check; "list has no scan, we must finish it in one go", 902-904). So the main thread stalls for the whole list, whatever the budget. Fixed upstream in 485425cec76e (2020-02-18): `scanLaterList` checks the time every 128 nodes and resumes next cycle from a quicklist bookmark.

**Arms.** Parent df45fed050d6 against the fix 485425cec76e, release builds with the bundled jemalloc (`tools/reproduce/build.sh`: GCC 15.3, `-O2`; both binaries contain `je_get_defrag_hint`), fresh server per run, port 15443, server and probe pinned to different cores. Defrag settings in both: `--hz 100`, `active-defrag-cycle-min` and `-max` 25 (so a 2,500 µs budget per cycle), `active-defrag-threshold-lower 10`, `active-defrag-ignore-bytes 10mb`, `list-max-ziplist-size 5`, `--latency-monitor-threshold 1`. Arms alternated per repetition, 5 repetitions, under the machine lock.

**Workload** (the fix's own test, `tests/unit/memefficiency.tcl`, larger): two lists filled alternately with 2,500,000 100-byte items each (Lua batches), so their nodes interleave in the same slabs; `DEL` of one list leaves every slab about half free (allocator fragmentation 2.0; `DEBUG OBJECT` of the kept list: 500,000 nodes of 5 entries). Measured: a PING every 1 ms on its own connection and core (`tools/reproduce/pingprobe.py`), 3 s of baseline, then `CONFIG SET activedefrag yes`; the window ends 2 s after `active_defrag_running` returns to 0. Server and main-thread CPU, peak RSS, and the server's `LATENCY HISTORY active-defrag-cycle`.

**Results** (mean, sd over 5 runs per arm; `results.md`):

| defragging one 500,000-node list | parent | fix | parent / fix |
|---|---|---|---|
| longest defrag cycle (`LATENCY HISTORY`) | 177.4 ms (sd 3.4) | 3 ms | 59 |
| worst PING round trip | 177.8 ms (sd 3.2) | 4.5 ms (sd 1.1) | 40 |
| p99.9 from the scheduled send | 173.1 ms | 3.3 ms | 52 |
| PINGs over 100 ms per run | 1 | 0 | |
| p99 PING round trip | 0.14 ms | 2.63 ms | 0.05 |
| defrag wall time | 0.57 s | 2.48 s | 0.23 |
| allocations moved (`active_defrag_hits`) | 616,432 | 621,300 | 0.99 |
| fragmentation before → after | 2.0 → 1.0 | 2.0 → 1.0 | |
| server CPU | 0.28 s | 0.60 s (sd 0.03) | 0.47 |
| peak RSS | 654.9 MB | 654.8 MB | 1.0 |

Both arms do the same work (the same allocations moved, fragmentation from 2.0 to 1.0); the parent does it in one 175-184 ms stall that ignores its 2.5 ms budget, the fix in 2.5 ms slices. The price of the fix is visible too: a p99 of 2.6 ms while defrag runs (its slices are back to back at the 25% duty cycle), four times the wall time, and twice the CPU. The bug is in latency.

## Files

- [`repro/run.py`](repro/run.py)

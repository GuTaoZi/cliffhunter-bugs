# P34 redis-unknown-type-costed-1 — UNLINK frees a stream inline, costed as one allocation

Queue rank 56 of `bugs/tables/queue.tsv` (severity 4, relevance 4, two raters). Reproduced on 2026-10-28 in the main session; the report follows. Code: `bugs/systems/redis/unknown-type-costed-1/repro/`; raw data: `data/experiments/redis-unknown-type-costed-1/raw/`.

**The bug.** Redis's lazy free estimates the cost of freeing a value (`lazyfreeGetFreeEffort`, `src/lazyfree.c` at 43af28f5b487, lines 31-47) and frees it on the main thread when the estimate is at most `LAZYFREE_THRESHOLD` (64, line 53; decision at 65-85). Lists, sets, sorted sets and hashes are costed by their element count; a stream has no branch and falls into `return 1; /* Everything else is a single allocation. */`, so `UNLINK` of a stream of any size frees it inline (`freeStream`: every rax node, listpack and consumer-group PEL entry), and every client waits. Fixed upstream in 5b0a06af4899 (2020-08-25): a stream's effort is its rax node count plus its consumer groups' PEL sizes, so a large stream goes to the lazyfree background thread.

**Arms.** Parent 43af28f5b487 against the fix 5b0a06af4899, release builds (`tools/reproduce/build.sh`: GCC 15.3, `-O2`, jemalloc), fresh server per run (`--save "" --appendonly no`), port 15442, the server pinned to one core and the probe to another. Arms alternated per repetition, 5 repetitions, under the machine lock; then a control of 2 repetitions.

**Workload.** `CONFIG SET stream-node-max-entries 1` (so each entry is its own rax node and listpack), then 3,000,000 `XADD s * f v` (Lua batches of 100,000; `XLEN` checked). Measured: a PING every 1 ms on its own connection and core (`tools/reproduce/pingprobe.py`), and 2 s later `UNLINK s` from a second connection, timed; the window ends 3 s after `lazyfree_pending_objects` is back to 0. Server CPU, main-thread CPU and peak RSS over the window. The control deletes with `DEL`, which frees inline in both arms.

**Results** (mean, sd; `results.md`):

| deleting a 3,000,000-entry stream | parent | fix | parent / fix |
|---|---|---|---|
| `UNLINK` round trip | 167.8 ms (sd 8.1) | 0.22 ms (sd 0.03) | 777 |
| worst PING round trip | 167.3 ms | 3.4 ms | 49 |
| p99.9 from the scheduled send | 162.6 ms | 3.0 ms | 55 |
| time the server did not answer (beyond 1 ms) | 169.9 ms | 5.8 ms | 29 |
| time until the memory is freed | 0 (inline) | 0.14 s (background) | |
| main-thread CPU | 0.256 s | 0.094 s | 2.7 |
| server CPU, all threads | 0.28 s | 0.22 s | 1.26 |
| peak RSS | 178.0 MB | 178.1 MB | 1.0 |
| control, `DEL` round trip (n=2) | 172.0 ms | 184.8 ms | 0.93 |

`INFO commandstats` agrees: the parent's `UNLINK` took 171,594 µs in the server, the fix's 20 µs, with `lazyfree_pending_objects` at 1 for about 150 ms while the background thread freed the stream (`used_memory` falling from 175 MB to 1 MB). The control shows the stall is the inline free itself: `DEL`, inline in both arms, blocks both for 172-185 ms. The bug is in latency, and only for the command that promises not to block.

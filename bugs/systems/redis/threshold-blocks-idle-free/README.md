# redis/threshold-blocks-idle-free

A threshold that blocks freeing when idle (parent of 0a9377535b6f vs the fix): accounted memory 1.98x, RSS 1.07x

- **Upstream:** fixed upstream in 0a9377535b6f (<https://github.com/redis/redis/commit/0a9377535b6f> <https://github.com/redis/redis/pull/9322>)
- **Effect:** memory, strong: accounted memory 1.98x, RSS 1.07x
- **Experiment:** P4, report: [experiments/reproductions/redis-threshold-blocks-idle-free/README.md](../../../../experiments/reproductions/redis-threshold-blocks-idle-free/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); an open-file limit above 5,100

**Build:**

```sh
tools/reproduce/build.sh redis 3f3f678a4741
tools/reproduce/build.sh redis 0a9377535b6f
```

**Run:**

```sh
ulimit -n 20000
python3 bugs/systems/redis/threshold-blocks-idle-free/repro/run.py
python3 tools/reproduce/summarize.py experiments/reproductions/redis-threshold-blocks-idle-free > experiments/reproductions/redis-threshold-blocks-idle-free/summary.json
```

**Writes:** data/experiments/redis-threshold-blocks-idle-free/raw/runs.jsonl and server.log (replaced), the summary.json

**Minutes:** about 3

**Notes:** One process opens 5,000 client sockets, hence the ulimit. Port 15412. The result is memory Redis accounts (client query buffers, used_memory), so it does not depend on the machine.

## The report

Copied from [`experiments/reproductions/redis-threshold-blocks-idle-free/README.md`](../../../../experiments/reproductions/redis-threshold-blocks-idle-free/README.md).

### P4 redis/threshold-blocks-idle-free — reproduced: idle clients double the memory Redis accounts for

**Bug.** `clientsCronResizeQueryBuffer()` (`server.c`) trimmed an idle client's query buffer
only if the buffer was larger than 32 KB, so idle clients whose buffers were below that kept them
forever. Fixed by 0a9377535b6f (2021-08-06), which drops the size threshold for idle clients.

**Builds:**

| arm | commit |
|---|---|
| buggy | 3f3f678a4741, the parent of the fix |
| fixed | 0a9377535b6f |

Both are `-O2`, jemalloc.

**Workload** (`run.py`): a fresh server per run. 5,000 clients connect, each sends one `PING`,
then all stay idle for 5 s, by which time the cron has visited every client. There are 5
repetitions, interleaved, plus a drift run.

#### Result (`summary.json`)

| arm | runs | `used_memory` added by the clients | idle query buffers | per client | server RSS | CPU while idle |
|---|---|---|---|---|---|---|
| buggy | 6 | **197.2 MB** | **97.6 MB** | 20 KB | 55.8 MB | 0.3% |
| fixed | 5 | **99.5 MB** | 0.02 MB | ~0 | 52.0 MB | 0.3% |

The memory Redis accounts for is 1.98× higher, and that is the number `maxmemory` eviction acts
on. Physical RSS rises only 1.07×, because the kept buffers are allocated but never touched.

## Files

- [`repro/run.py`](repro/run.py)
- [`fix/upstream-redis-threshold-blocks-idle-free.diff`](fix/upstream-redis-threshold-blocks-idle-free.diff)

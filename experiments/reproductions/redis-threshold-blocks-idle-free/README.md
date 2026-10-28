# P4 redis/threshold-blocks-idle-free — reproduced: idle clients double the memory Redis accounts for

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

## Result (`summary.json`)

| arm | runs | `used_memory` added by the clients | idle query buffers | per client | server RSS | CPU while idle |
|---|---|---|---|---|---|---|
| buggy | 6 | **197.2 MB** | **97.6 MB** | 20 KB | 55.8 MB | 0.3% |
| fixed | 5 | **99.5 MB** | 0.02 MB | ~0 | 52.0 MB | 0.3% |

The memory Redis accounts for is 1.98× higher, and that is the number `maxmemory` eviction acts
on. Physical RSS rises only 1.07×, because the kept buffers are allocated but never touched.

# P8 valkey/memory-guard-blocks-shrink — reproduced: lowering maxmemory evicts 99.9% of keys

**Bug.** `resize()` (`hashtable.c`) asked the `resizeAllowed` guard (`server.c`) before every new
table allocation. The guard refuses an allocation that would cross `maxmemory`, and it also
refused **shrinks**, which allocate briefly but end up saving memory. After `maxmemory` is lowered,
the key table cannot shrink, its bucket array alone stays over the limit, and eviction keeps
removing keys. Fixed by 130ea3973ba9 (2025-07-04), which lets shrinks cross `maxmemory`.

**Builds:**

| arm | commit |
|---|---|
| buggy | 61b63ab98997, the parent of the fix |
| fixed | 130ea3973ba9 |

Both are `-O3`, jemalloc.

**Workload** (`run.py`, the commit's own recipe): a fresh server per run with `maxmemory 2gb` and
`allkeys-lru`. Run `DEBUG POPULATE 20000000`, then `CONFIG SET maxmemory 200mb`, then poll for
30 s. CPU and peak memory come from `tools/reproduce/measure.py` over those 30 s. There are 3 repetitions,
interleaved, plus a drift run.

## Result (`summary.json`, `raw/runs.jsonl`)

| arm | runs | keys left of 20,000,000 | `used_memory` vs 200 MB limit | key table buckets | CPU in 30 s |
|---|---|---|---|---|---|
| buggy | 4 | **6,064–21,456** | 258 MB, over the limit | 29,360,128 (never shrinks) | **30.1 s** (a full core) |
| fixed | 3 | **2,578,544–2,593,994** | 199 MB | 7,340,032 | 19.0 s |

With the buggy guard the server keeps 0.7% as many keys, stays 1.3× over its memory limit, and
spends 1.58× the CPU evicting keys it did not need to evict.

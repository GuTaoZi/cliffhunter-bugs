# P51 memcached-counter-never-decremented — counter never decremented

Queue rank 88 of `bugs/tables/queue.tsv` (severity 3, relevance 4.5, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/memcached/counter-never-decremented/repro/`; raw data: `data/experiments/memcached-counter-never-decremented/raw/`.

- **verdict:** confirmed in latency, on a CPU-confined server.
  - The design rated it doubtful. The parent's LRU crawler never sleeps, because its sleep counter is never counted down.
  - On a server confined to 2 CPUs, closed-loop multigets during continuous crawls serve **1.04M keys/s at p99 4.07 ms** on the parent, against the fix's **1.90M at 255 us** (1,000 us crawler sleep), or 1.68M at 268 us (the default 100 us).
  - The median is unchanged (60 against 61 us). The tail sits at about 4 ms, the size of a scheduler slice: the unthrottled crawler thread takes one of the two CPUs, and workers wait behind it.
  - Without crawls (phase 0) the arms are equal, at 2.15M keys/s and p99 93 us.
  - Server CPU during the crawls is 1.13-1.18x; peak RSS is equal.

- **arms:** parent 117dc8dd1f78, fix 917110af97fa ("crawler now uses rate limiter sleeps :(", 2016-07-30). Both are built by `tools/reproduce/build.sh memcached` (-O2, gcc 15.3.0).

- **workload:** `run.py check`, then `run.py measure 1000 4` and `run.py measure 100 3`, with the arms alternating.
  - A fresh server with `taskset -c 0-1`, `-t 2`, 1 GB, `-o lru_crawler,lru_crawler_sleep=S,hashpower=21`.
  - 1,000,000 keys of 100 bytes.
  - Phase 0: 10 s of closed-loop 16-key multigets from 8 client processes pinned to CPUs 16-23.
  - Phase 1: 30 s of the same, with `lru_crawler crawl all` requested every 2 ms.
  - Per phase: request latency, keys/s, the server's CPU and peak RSS (`tools/reproduce/measure.py`), and `crawler_items_checked`.

- **results** (results.md):

| sleep | measure | parent | fix | parent / fix |
|---|---|---|---|---|
| 1,000 us | phase 0 keys/s / p99 | 2.15M / 92.8 us | 2.16M / 92.7 us | 1.00 / 1.00 |
| 1,000 us | phase 1 keys/s | 1.04M | 1.90M | 0.55 |
| 1,000 us | phase 1 p50 / p99 / p99.9 | 60 / 4,066 / 5,088 us | 61 / 255 / 279 us | 0.98 / 15.9 / 18.3 |
| 1,000 us | phase 1 server CPU / peak RSS | 51.0 s / 202.8 MB | 43.3 s / 202.8 MB | 1.18 / 1.00 |
| 100 us (default) | phase 1 keys/s / p99 | 1.04M / 4,068 us | 1.68M / 268 us | 0.62 / 15.2 |
| 100 us | phase 0 keys/s / p99 | 2.16M / 92.8 us | 2.17M / 91.3 us | 0.99 / 1.02 |

  The decision check (`data/check.json`, 200,000 items, crawler sleep 5,000 us): one crawl of everything takes 0.036 s on the parent, which ignores the sleep, and 1.157 s on the fix.
  `crawler_items_checked` per second during phase 1 is lower on the parent (83k against 800k). The crawl requests are mostly answered BUSY while a crawl is running, so the counter does not measure the crawler's duty. It is recorded, not interpreted.

- **mechanism** (at 117dc8dd1f78):
  - The crawler thread tests `if (crawls_persleep <= 0 && settings.lru_crawler_sleep)` (`items.c:1403`) after each item.
  - Its local `crawls_persleep` (`:1341`) is never decremented, so the thread never sleeps.
  - The fix is `crawls_persleep-- <= 0` (`items.c:1403@917110af97fa`).
  - With CPUs to spare, the crawler's extra duty costs little. Confined to 2 CPUs, it takes CPU time the workers need.

- **what did not work:** the design expected the effect to be small at the default sleep. It is as large as at 1,000 us when the CPUs are scarce.

- **files:** `run.py`; `data/` (`runs.jsonl`, `check.json`, server logs); `design.md` (verbatim, which also covers memcached/clock-underflow); `results.md`.

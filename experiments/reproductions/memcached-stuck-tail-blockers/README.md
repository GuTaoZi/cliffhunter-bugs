# P21 memcached-stuck-tail-blockers — referenced items stuck at the tail refuse every write

Queue rank 6 of `bugs/tables/queue.tsv` (severity 4.5, relevance 4.5, two raters). Run on 2026-10-22/23 by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`), which stopped before writing its report; the report below was written in the main session on 2026-10-27 from the agent's data. Code: `bugs/systems/memcached/stuck-tail-blockers/repro/`; raw data: `data/experiments/memcached-stuck-tail-blockers/raw/`.

Queue rank 6 of `bugs/tables/queue.tsv` (severity 4.5, relevance 4.5, cost low; two raters). Reproduced on 2026-10-22/23 by a reproduction agent (`data/agents/prompts/23-reproduce-one-queued-bug.md`), which stopped at a session limit before writing its report; its campaign had finished and `results.md` (generated from `data/runs.jsonl`) is complete. Filed on 2026-10-27 from that data; nothing was re-run.

**The bug.** memcached's LRU tail walk (`items.c`, `do_item_alloc`) looks at no more than five items from the tail for one it can evict. An item with a reference held cannot be evicted. A client that multi-gets keys and never reads its socket keeps a reference on every fetched item until the reply is written. Once unpopular, those items drift to the tail; the five-item search then finds only referenced items and every write to the slab class fails with `SERVER_ERROR out of memory`. Fixed upstream in f2a4e5b491ed ("Avoid OOM errors when locked items stuck in tail", 2014): a referenced tail item older than the update interval is moved back to the head, so the search reaches evictable items.

**Arms.** Buggy parent 4234cbad76c9 against the fix f2a4e5b491ed, release builds (`-O2 -DNDEBUG`, gcc), 4 threads, port 15440. Arms interleaved, order alternated per repetition, under the machine lock (`campaign.sh`).

**Workload** (`stuck_tail.py`): fill one slab class until it evicts; a client sets a small receive buffer, multi-gets the oldest live keys and never reads; optionally wait 63 s so those items are older than `ITEM_UPDATE_INTERVAL` (60 s); then a writer sets new keys of the same size one at a time and records each reply and its latency (measured phase); then counters, a hit check, the client's disconnect and 50 recovery sets.

**Results** (mean over repetitions; full tables in `results.md`):

| configuration | repetitions | writes refused, parent | writes refused, fix | server CPU, parent / fix | peak RSS |
|---|---|---|---|---|---|
| refhang: -m 6, 66,560 B values, 120 keys, hang on 115 | 5 | 2,000 of 2,000 | 0 (2,000 evictions) | 0.06 / 0.10 s | 8.8 / 9.0 MB |
| thousands-aged: -m 64, 2,048 B, 40,000 keys, hang on 3,000, aged 63 s | 3 | 20,000 of 20,000 | 3 | 0.32 / 0.31 s | 67.6 MB both |
| thousands-fresh: the same, not aged | 5 | 20,000 of 20,000 | 20,000 of 20,000 | 0.27 / 1.96 s | 67.6 MB both |

The parent refuses every write in all three configurations; the fix stores them once the stuck items are older than the update interval (refhang, thousands-aged). With fresh items (thousands-fresh) the fix still refuses them all: its relief applies only to items older than 60 s, and it spends 7x the server CPU moving items without freeing any (a negative condition of the fix, recorded as found). Writes recover in both arms once the client disconnects (50 of 50). Latency is lower for the parent because a refusal is answered at once (p99 88 vs 131 us in refhang): the cost of this bug is availability (refused writes) and lost cache contents, not latency.

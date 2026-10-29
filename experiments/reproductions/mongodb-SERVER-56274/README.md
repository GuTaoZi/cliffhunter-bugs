# P43 mongodb-SERVER-56274 — an index seek past invisible entries walks them twice without cursor bounds

A bug the metrics-recommendation collaborators study (meeting of 2026-10-28, docs/weekly/2026-10-28/); not in the queue. Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/mongodb/SERVER-56274/repro/`; raw data: `data/experiments/mongodb-SERVER-56274/raw/` (not copied, too large: runs/ (2354 MB); they stay in the data root's repro/ directory).

- **verdict:** confirmed in latency.
  - An index seek past the last visible key, with 1,000,000 index entries the reader cannot see after that key, takes **1,359 ms on MongoDB 7.0.45 and 0.19 ms on 8.2.12**.
  - The server's CPU per seek is 1,368 ms against 0.33 ms.
  - On 7.0.45 each seek steps over all 1,000,000 entries forwards and again backwards; on 8.2.12 it steps over none.
  - A control query, which both versions must answer by walking the run backwards, takes 676 against 622 ms (1.09x). So the seek's difference is the missing cursor bound, not a general version difference.
  - Peak RSS is equal (480 against 485 MB).

- **arms:** there is no switch inside one binary.
  - SERVER-55750 is an unrelated flag; see design.md, section 0.
  - The arms are the official release tarballs: 7.0.45 (b345c2303bcb, ubuntu2204, unbounded) and 8.2.12 (10d50f5046de, ubuntu2404, bounded).
  - Both are run the same way, through Nix's glibc loader (`ld-linux-x86-64.so.2 --library-path`) with OpenSSL 3.6.4 and curl 8.22.0, because this host has no system loader.
  - Both have WiredTiger's deleted-page skipping (WT-10807), so the remaining difference in the walk is the server's bounded cursors.

- **workload:** `run.py measure 3`, with the arms alternating.
  - A fresh single-node replica set: pinned to CPUs 0-7, 2 GB cache, `transactionLifetimeLimitSeconds` 3600.
  - Documents `_id` 1..1000. A snapshot transaction is opened, and its read timestamp pinned by a find.
  - 1,000,000 more documents are inserted outside the transaction. They are invisible to it and sit at the tail of the `_id` index.
  - Inside the transaction, through `tools/probes/mongowire.py`:
    - **seek:** 50 queries `find({_id: {$gt: 5e6}}).hint({_id: 1}).limit(1)`;
    - **control:** 50 queries `find().hint({_id: 1}).sort({_id: -1}).limit(1)`.
  - Per loop: the client latency, the server's CPU (`/proc`), peak RSS (VmHWM, reset), and the WiredTiger cursor counters (`serverStatus().wiredTiger.cursor`).

- **results** (results.md; mean over 3 repetitions, per query):

| measure | 7.0.45 | 8.2.12 | ratio |
|---|---|---|---|
| seek latency | 1,359 ms (1,303-1,464) | 0.19 ms (0.10-0.25) | 7,257 |
| seek: server CPU | 1,368 ms | 0.33 ms | 4,103 |
| seek: entries skipped by next / by prev | 1,000,000 / 1,000,000 | 0 / 0 | |
| seek: search_near calls | 1 | 0 | |
| control latency | 676 ms | 622 ms | 1.09 |
| control: entries skipped by prev | 1,000,000 | 1,000,000 | |
| peak RSS | 480 MB | 485 MB | 0.99 |

- **mechanism** (design.md has every line):
  - On 7.0.45, an index seek is WiredTiger's `search_near`: `src/mongo/db/storage/wiredtiger/wiredtiger_index.cpp:1193@b345c2303bcb`, checked.
  - When nothing at or after the seek key is visible, `search_near` steps next over every invisible entry to the end of the tree, then back with prev: `src/third_party/wiredtiger/src/btree/bt_cursor.c:873-905`.
  - The server's SERVER-56839 loop then advances with next again: `wiredtiger_index.cpp:1225-1236`.
  - On 8.x the seek sets a bound and positions from it, stopping at the end of the tree: `wiredtiger_index.cpp:968-1006@10d50f5046de`.
  - The fix is a series of tickets from 6.2 to 8.1: SERVER-65528, 65527, 69093, 68380, 85261 and 88411.

- **what did not work, and limits:**
  - The arms are different releases, so the control is the guard against a general difference; it is 1.09x.
  - The trigger is entries invisible to an open snapshot, not committed deletes. Deleted entries that are visible to all are cleaned by forced eviction after the first walk, so they give one slow query, not a repeatable one.
  - The SERVER-56274 ticket itself was not read; the link from the ticket to these code paths is the design's.
  - The data directories (2.3 GB) stay in the data root.

- **files:** `run.py`; `data/` (`runs.jsonl`, the per-query latencies); `design.md` (the read-only design, verbatim); `results.md`.

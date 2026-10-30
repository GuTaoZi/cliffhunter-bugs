# P49 postgres-gave-up-advising-early — gave up advising early

Queue rank 70 of `bugs/tables/queue.tsv` (severity 3, relevance 5, two raters). Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/postgres/gave-up-advising-early/repro/`; raw data: `data/experiments/postgres-gave-up-advising-early/raw/`.

- **verdict:** confirmed in latency, with a cost in the other direction.
  - A cold VACUUM whose stream is dense runs of 48 blocks separated by skipped gaps takes **15.2 s on the parent and 10.5 s on the fix** (1.44x). VACUUM's own read time is 14.9 against 10.3 s.
  - Both arms read the same 875 MB from the device and leave the same pages resident, so the difference is how the reads overlap, not how much is read.
  - Server CPU (0.67 against 0.62 s) and peak RSS (37 MB) are equal.
  - Two results change the reading:
    - **With advice off** (`maintenance_io_concurrency` 0) both arms take 10.4 s. So on this disk the parent's advice of only the first chunk after each jump is slower than no advice at all. The fix removes that penalty but does not beat no advice.
    - **The 16-block control** was designed to be equal: each run is one chunk, advised in both arms. Instead the fix is slower, 5.84 against 3.88 s (1.5x), with the same bytes read. For runs of a single chunk the fix advises less, or advises worse, than the parent.

- **arms:** parent 11bd8318602f, fix 7ea8cd15661e ("Improve read_stream.c advice for dense streams.").
  - Both are built by `tools/reproduce/build.sh postgres` (-O2, gcc 15.3.0).
  - The same catalog version, so one data directory serves both.

- **workload:**
  - `run.py setup`, then `run.py measure t48 5`, `measure t16 3` and `measure t48 3 mic0`, with the arms alternating.
  - Two tables of 400,000 blocks (3.3 GB each), one row per 8 kB block (a 5,000-byte plain pad), frozen.
  - Then, in a prepared transaction never resolved, the rows of a run of R blocks in every 400 are deleted (R 48 for t48, 16 for t16). VACUUM must scan the runs and can never prune them, so each VACUUM is read-only and repeatable: "0 dirtied" in every run.
  - One run:
    - the table's files are dropped from the page cache (fsync, POSIX_FADV_DONTNEED; `fincore` showed 0 resident pages before every run);
    - the arm's server starts (shared_buffers 512 MB, autovacuum off, track_io_timing on);
    - `VACUUM (VERBOSE)` is timed, with the server's CPU and peak RSS (`tools/reproduce/measure.py` Sampler), VACUUM's reported read time, the device's sectors read (`/sys/block/sda/stat`) and the resident pages after.
  - The disk is the host's rotational hardware RAID, ext4.

- **results** (results.md):

| table | measure | parent | fix | parent / fix |
|---|---|---|---|---|
| t48 (trigger) | VACUUM wall time | 15.20 s | 10.53 s | 1.44 |
| t48 | VACUUM read time | 14.85 s | 10.27 s | 1.45 |
| t48 | read rate | 24.8 MB/s | 35.7 MB/s | 0.69 |
| t48 | device MB read / resident pages after | 875 / 224,198 | 876 / 224,198 | 1.00 / 1.00 |
| t48 | server CPU / peak RSS | 0.67 s / 37.1 MB | 0.62 s / 37.1 MB | 1.07 / 1.00 |
| t48, advice off | VACUUM wall time | 10.38 s | 10.41 s | 1.00 |
| t16 (control) | VACUUM wall time | 3.88 s | 5.84 s | 0.66 |
| t16 | device MB read | 126.1 | 126.1 | 1.00 |

- **mechanism** (at 11bd8318602f):
  - A started read is advised only when `pending_read_blocknum != seq_blocknum` (`src/backend/storage/aio/read_stream.c:269-272`), that is, for the first io_combine_limit-sized read after a jump. The rest of a dense run is read synchronously when the consumer reaches it.
  - VACUUM's stream (`src/backend/access/heap/vacuumlazy.c:1229`) is dense runs separated by skipped all-visible gaps of at least 32 blocks.
  - The fix keeps advice on for a run's sequential reads until the consumer reaches its first I/O (`seq_until_processed`, `read_stream.c:277-289,879-881@7ea8cd15661e`).
  - Not shown here: how often each arm calls `posix_fadvise`. The design's strace count was left out, because tracing changes the timing. The t16 result suggests the fix advises a jump only when buffers are already pinned (`:288-289@7ea8cd15661e`); that was not tested.

- **what did not work:**
  - The design expected the parent's kernel read-ahead to overshoot into the gaps; resident pages are equal in both arms.
  - It expected t16 to be equal; the fix is 1.5x slower there.
  - Both are recorded as they came out.

- **files:** `run.py`; `data/` (`runs.jsonl`, `setup.json`, each VACUUM's verbose output); `design.md` (verbatim, which also covers postgres/waiter-count-oscillates); `results.md`. The data directory (6.6 GB) stays in the data root.

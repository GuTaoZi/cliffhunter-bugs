# mongodb/SERVER-44991

SERVER-44991 (WiredTiger WT-5319): reconciliation of prefix-compressed pages read from disk rebuilds every key; on tmpfs checkpoints 1.74x longer (653 vs 375 ms), evicting updates 0.60x the throughput and 1.66x the p99; on disk only CPU (1.37x) and the update tail (1.24-1.36x) separate; peak RSS equal

- **Upstream:** fixed upstream in WiredTiger 99636a29c679 (WT-5319, 2019-12-14)
- **Effect:** latency, strong: a checkpoint of prefix-compressed pages read back from disk takes 653 vs 375 ms on tmpfs (1.74x), updates that evict in a 64 MB cache reach 0.60x the throughput with 1.66x the p99; on disk the checkpoint's I/O hides it (CPU 1.37x, update tail 1.24-1.36x); peak RSS equal
- **Experiment:** P42, report: [experiments/reproductions/mongodb-SERVER-44991/README.md](../../../../experiments/reproductions/mongodb-SERVER-44991/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); about 5 GB of free disk and 1 GB of tmpfs

**Build:**

```sh
tools/reproduce/build.sh wiredtiger 33204938da7b
tools/reproduce/build.sh wiredtiger 99636a29c679
```

**Run:**

```sh
python3 bugs/systems/mongodb/SERVER-44991/repro/run.py measure 5 disk
python3 bugs/systems/mongodb/SERVER-44991/repro/run.py measure 5 mem
python3 bugs/systems/mongodb/SERVER-44991/repro/run.py report
```

**Writes:** repro/data/runs.jsonl (appended), repro/data/*-load.txt, *-ckpt.txt, *-evict.txt, repro/results.md

**Minutes:** about 25

**Notes:** run.py compiles wt5319.c against each arm's library. Homes are kept: repro/homes/ (disk cell, about 450 MB each) and /dev/shm/ch-wt5319-mem-* (mem cell). report averages every row of data/runs.jsonl: delete it before a re-run.

## The report

Copied from [`experiments/reproductions/mongodb-SERVER-44991/README.md`](../../../../experiments/reproductions/mongodb-SERVER-44991/README.md).

### P42 mongodb-SERVER-44991 — WiredTiger reconciliation rebuilds every prefix-compressed key after the saved key is cleared

A bug the metrics-recommendation collaborators study (meeting of 2026-10-28, docs/weekly/2026-10-28/), in MongoDB's storage engine; not in the queue. Reproduced on 2026-10-29 in the main session; the report follows. Code: `bugs/systems/mongodb/SERVER-44991/repro/`; raw data: `data/experiments/mongodb-SERVER-44991/raw/` (not copied, too large: homes/ (4694 MB); they stay in the data root's repro/ directory).

- **verdict:** confirmed, in latency, when reconciliation is not hidden by disk I/O.
  - On tmpfs, checkpoints take 1.74x as long on the parent (653 against 375 ms).
  - Updates that evict in a 64 MB cache run at 0.60x the throughput (9,526 against 15,770 per second), with 1.66x the p99 (4.29 against 2.58 ms).
  - On disk, each checkpoint writes and syncs about 270 MB. The checkpoint's latency is then dominated by I/O and does not separate the arms (parent 1,774, sd 388 ms; fix 2,155, sd 168 ms). The checkpoint's CPU is still 1.37x on the parent, and the update tail is 1.24x at p99 and 1.36x at p99.9.

- **arms:** the parent is 33204938da7b, at `build/wiredtiger-33204938da7b`. The fix is 99636a29c679, at `build/wiredtiger-99636a29c679`.
  - Both are built by `tools/reproduce/build.sh wiredtiger COMMIT`: the autotools tree of 2019, gcc 15.3.0, -O2, `-std=gnu11 -fcommon`, static library.
  - The driver `wt5319.c` is compiled against each arm's own `libwiredtiger.a` and `wiredtiger.h`, at -O2.

- **workload:** `run.py measure 5 disk` and `run.py measure 5 mem`, with arms alternating per repetition. Each step goes through `tools/reproduce/runcmd.py`.
  - **load:** 2,000,000 keys of 32 zero-padded digits, so neighbouring keys share a long prefix. The table is `prefix_compression=true` with 32 KB leaf pages. Keys are bulk-loaded, checkpointed and closed.
  - **ckpt:** the table is reopened, so every key on a page read back is a cell, not an instantiated key. Then 5 rounds of: update every 64th key (every leaf page dirty), then a timed `WT_SESSION::checkpoint`, which reconciles every leaf page.
  - **evict:** 8 threads update random keys for 30 s in a 64 MB cache, so application threads evict and reconcile pages inside their updates. The measure is per-update latency (a histogram, 100 buckets per decade).
  - **Cells:**
    - **disk:** 100-byte values, a fresh home per repetition on disk.
    - **mem:** 16-byte values on tmpfs. Key building is then the main work per page. There is one load per arm, reused, since every run reopens the table and reads its pages back cold.

- **results** (`results.md`; mean, with the spread there):

| cell | measure | parent | fix | parent / fix |
|---|---|---|---|---|
| mem | checkpoint latency, rounds 2-5 | 653 ms | 375 ms | 1.74 |
| mem | checkpoint CPU (process) | 3.03 s | 1.74 s | 1.74 |
| mem | pages reconciled per checkpoint run | 7,849 | 7,849 | 1.00 |
| mem | updates per second, 64 MB cache | 9,526 | 15,770 | 0.60 |
| mem | update p50 / p99 / p99.9 | 32.5 / 4,286 / 6,398 us | 35.3 / 2,582 / 6,376 us | 0.92 / 1.66 / 1.00 |
| mem | pages reconciled by eviction in 30 s | 242,500 | 399,700 | 0.61 |
| mem | application time evicting (8 threads, 30 s) | 223 s | 221 s | 1.01 |
| mem | peak RSS (checkpoint step) | 147 MB | 145 MB | 1.01 |
| disk | checkpoint latency, rounds 2-5 | 1,774 ms | 2,155 ms | 0.82 |
| disk | checkpoint CPU (process) | 6.58 s | 4.81 s | 1.37 |
| disk | update p99 / p99.9 | 754 / 1,402 us | 606 / 1,031 us | 1.24 / 1.36 |
| disk | updates per second | 49,320 | 48,620 | 1.01 |

  In the eviction phase both arms spend the same application time evicting. In that time the fix reconciles 1.65x as many pages, so each reconciliation costs 1.65x as much on the parent, and update throughput follows.

- **mechanism** (all at 33204938da7b unless noted):
  - `src/reconcile/rec_row.c:922` passes the saved previous key's outputs to the helper: `__wt_row_leaf_key_info(page, copy, NULL, &cell, &tmpkey->data, &tmpkey->size)`.
  - For an on-page cell key, which has no instantiated key, `src/include/btree.i:841-844` sets `*datap = NULL; *sizep = 0`.
  - So the fast path `rec_row.c:928`, `tmpkey->size >= kpack->prefix`, fails for every prefix-compressed key. Its job is to append the key's suffix to the previous key.
  - Each key is instead rebuilt by `__wt_row_leaf_key_copy` (`rec_row.c:947`), which walks back to the nearest instantiated key (key_gap 10, `src/config/config_def.c`) and rolls forward.
  - The fix 99636a29c679 deletes the four clearing lines. The helper then leaves the caller's buffer as it was, and the fast path holds for every key after the first.
  - In D10 (`experiments/finding/2026-10-28-wt-coverage/`), the same decision at 0a21d382fe was taken in 272.5M of 274.2M evaluations under test/format, at the fix. That is the share this bug drives down.

- **what did not work:**
  - At 200,000 keys on disk the smoke test showed the checkpoint 1.7x slower on the parent.
  - At 2,000,000 keys with 100-byte values on disk, the checkpoint's write and sync dominate and vary by about 20% between runs. The latency comparison there is inconclusive; only CPU and the update tail separate.
  - The in-memory cell was added for that reason.
  - Homes are kept, not deleted:
    - ten 450 MB homes under `homes/`;
    - two on tmpfs, `/dev/shm/ch-wt5319-mem-*`.

- **files:**
  - `run.py` and `wt5319.c`, the driver.
  - `data/`: one runcmd output per step and `runs.jsonl`.
  - `results.md`, `measure.out`, `measure-mem.out`.

## Files

- [`repro/run.py`](repro/run.py)
- [`repro/wt5319.c`](repro/wt5319.c)

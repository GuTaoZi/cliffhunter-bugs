# rocksdb/unbounded-search

An unbounded search (parent of 88bc91f3cc2b vs the fix): 15.4x CPU, 0.066x throughput

- **Upstream:** fixed upstream in 88bc91f3c (<https://github.com/facebook/rocksdb/commit/88bc91f3c> <https://github.com/facebook/rocksdb/pull/12141>)
- **Effect:** latency, strong: throughput 0.066x (15x slower), CPU 15.4x
- **Experiment:** P6, report: [experiments/reproductions/rocksdb-unbounded-search/README.md](../../../../experiments/reproductions/rocksdb-unbounded-search/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); 12 free cores; about 2.3 GB of RAM

**Build:**

```sh
tools/reproduce/build.sh rocksdb cd577f605948
tools/reproduce/build.sh rocksdb 88bc91f3cc2b
```

**Run:**

```sh
python3 bugs/systems/rocksdb/unbounded-search/repro/run.py
python3 tools/reproduce/summarize.py experiments/reproductions/rocksdb-unbounded-search > experiments/reproductions/rocksdb-unbounded-search/summary.json
```

**Writes:** data/experiments/rocksdb-unbounded-search/raw/{buggy,fixed}-*.txt and runs.jsonl (replaced), the summary.json

**Minutes:** about 10

**Notes:** cache_bench runs 12 threads; with fewer free cores the buggy arm's 81 s runs stretch.

## The report

Copied from [`experiments/reproductions/rocksdb-unbounded-search/README.md`](../../../../experiments/reproductions/rocksdb-unbounded-search/README.md).

### P6 rocksdb/unbounded-search — reproduced: a mostly pinned HyperClockCache runs 15× slower

**Bug.** To insert into a full HyperClockCache shard, eviction sweeps the clock until it has
freed enough unpinned space (`cache/clock_cache.cc`). When almost every entry is pinned, nothing
bounds the sweep, and every cache miss pays for a long search. The commit says "the CPU cost of
each cache miss could fall off a cliff". Fixed by 88bc91f3cc2b (2023-12-14), which adds
`eviction_effort_cap` (default 30). Once the cap is reached, the insert goes over capacity instead
of searching further.

**Builds:**

| arm | commit |
|---|---|
| buggy | cd577f605948, the parent of the fix |
| fixed | 88bc91f3cc2b |

Both are `DEBUG_LEVEL=0`. The binary records `-O2`, and db_bench contains no "Assertions are
enabled" string, so NDEBUG was set (`flags.txt`).

**Workload** (`run.py`, the commit's own command):
`cache_bench -cache_type=auto_hyper_clock_cache -threads=12 -histograms=0 -pinned_ratio=1.7`,
which is 24,000,000 operations against a 1 GB cache. Wall time, CPU and peak RSS come from
`tools/reproduce/runcmd.py` (getrusage of the benchmark process, which contains the cache). There are 5
interleaved repetitions plus a drift run.

#### Result (`summary.json`, `raw/runs.jsonl`)

| arm | runs | ops/s | wall | CPU | CPU per million ops | peak RSS |
|---|---|---|---|---|---|---|
| buggy | 6 | **300,000** (279k–318k) | 81.1 s | 961 s | **40.0 s** | 2,262 MB |
| fixed | 5 | **4,551,000** (4.53M–4.59M) | 6.1 s | 62.4 s | **2.60 s** | 2,233 MB |

Buggy/fixed CPU is **15.4× (95% CI 14.4–16.3)**, throughput is 0.066×, and peak RSS is 1.03×
(1.00–1.06). The commit reports 141k → 1.98M ops/s (14×) on its own machine. The commit also
names the cost of the fix: with the cap an insert may go over capacity, and at cap 1 its RSS
doubled. At the default cap 30 we see no memory difference.

## Files

- [`repro/run.py`](repro/run.py)

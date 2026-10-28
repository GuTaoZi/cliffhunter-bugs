# postgres/uncounted-memory

Memory the aggregate never counts (parent of 85adc584e2bd vs the fix): 5.41x RSS, 1.14x time; a narrow workload shows 1.01x (the negative condition)

- **Upstream:** fixed upstream in 85adc584e2b (<https://github.com/postgres/postgres/commit/85adc584e2b>)
- **Effect:** memory, strong: RSS 5.41x (time 1.14x)
- **Experiment:** P3, report: [experiments/reproductions/postgres-uncounted-memory/README.md](../../../../experiments/reproductions/postgres-uncounted-memory/README.md)

## Run it

Paths are relative to the kit's root; `tools/reproduce/setup.sh` first (see the top README).

**Needs:** Nix; about 0.6 GB of RAM and 0.5 GB of temporary disk

**Build:**

```sh
tools/reproduce/build.sh postgres 9dbc53591a2d
tools/reproduce/build.sh postgres 85adc584e2bd
```

**Run:**

```sh
python3 bugs/systems/postgres/uncounted-memory/repro/run.py --tag -wide
python3 bugs/systems/postgres/uncounted-memory/repro/run.py --rows 2000000 --width 32 --work-mem 1MB
python3 tools/reproduce/summarize.py experiments/reproductions/postgres-uncounted-memory --runs runs-wide.jsonl > experiments/reproductions/postgres-uncounted-memory/summary.json
python3 tools/reproduce/summarize.py experiments/reproductions/postgres-uncounted-memory --runs runs.jsonl > experiments/reproductions/postgres-uncounted-memory/summary-narrow.json
```

**Writes:** data/experiments/postgres-uncounted-memory/raw/runs-wide.jsonl, runs.jsonl and plan-*.json (replaced), the two summaries

**Minutes:** about 4

**Notes:** The first run is the main result (wide rows); the second is the narrow-row negative condition, with flags taken from the report: the recorded narrow data came from an earlier version of run.py. Port 15431. raw/runs-probe.jsonl is an exploratory leftover.

## The report

Copied from [`experiments/reproductions/postgres-uncounted-memory/README.md`](../../../../experiments/reproductions/postgres-uncounted-memory/README.md).

### P3 postgres/uncounted-memory — reproduced: a sort keeps 8× its memory budget in RAM

**Bug.** `tuplesort_putdatum()` (`tuplesortvariants.c`) counted the memory of every
pass-by-reference datum as 0 bytes. Only the 24-byte sort slots were counted, so a sort of large
single-column values never saw `work_mem` exceeded and stayed in memory. Fixed by 85adc584e2bd
(2026-10-06). Diff read at the fix; the parent's code read in the parent build.

**Builds:**

| arm | commit |
|---|---|
| buggy | 9dbc53591a2d, the parent of the fix |
| fixed | 85adc584e2bd |

Both are `./configure`, `-O2`, assertions off.

**Workload** (`run.py`): a fresh server per run. One query:
`SELECT repeat(md5(i::text), 32) FROM generate_series(1,500000) i ORDER BY 1`
(500,000 values of 1 KB) with `work_mem=64MB`, no parallelism, no JIT. CPU and peak memory come from
`tools/reproduce/measure.py` over the server's process tree. There are 5 repetitions, interleaved, plus a drift run.

#### Result (`summary.json`, from `raw/runs-wide.jsonl`)

| arm | runs | sort method | backend peak RSS | CPU | execution time |
|---|---|---|---|---|---|
| buggy | 6 | in-memory quicksort, reporting "12,289 kB" | **539 MB** (538.5–539.1) | 1.41 s | 1,433 ms |
| fixed | 5 | external merge, 505 MB on disk | **99.6 MB** | 1.23 s | 1,264 ms |

Buggy/fixed: peak memory **5.41×** (95% CI 5.41–5.42), CPU 1.14× (1.09–1.19), time 1.14× (1.10–1.17).

The buggy sort reports 12 MB but holds 539 MB, 8.4× its 64 MB budget. It is also slower.

**Negative condition, kept** (`summary-narrow.json`, from `raw/runs.jsonl`): with narrow values
(a bare 32-character `md5`, 2,000,000 rows, `work_mem=1MB`), the counted slot array alone exceeds
`work_mem`. Both arms then spill identically: memory 1.01×, CPU 1.03×. The bug needs values much
larger than the 24-byte slot. The workload first suggested for this bug was this narrow one; it
would have shown nothing.

## Files

- [`repro/run.py`](repro/run.py)

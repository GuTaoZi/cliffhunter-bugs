# P2 postgres/tuples-mistaken-for-groups — reproduced: 30× too many spill batches

**Bug.** When a spilled HashAgg partition had to spill again, `nodeAgg.c` used the number of
*tuples* in the partition as its number of *groups*, so it split the partition into far too many
pieces. Fixed by 9878b643f37b (2020-07-28), which estimates the group count with HyperLogLog.

**Builds:**

| arm | commit |
|---|---|
| buggy | f2130e77da51, the parent of the fix |
| fixed | 9878b643f37b |

Both are `-O2 -std=gnu11 -fcommon`; GCC 15 needs the last two for 2020 code.

**Workload** (`run.py`): a fresh server per run. One query:
`SELECT k, count(*) FROM (SELECT i % 200000 AS k FROM generate_series(1,4000000) i) s GROUP BY k`
with `work_mem=64kB`, `enable_sort=off`, no parallelism. There are 5 repetitions, interleaved,
plus a drift run. A RocksDB rebuild was running on the same machine during these runs; absolute
times drift across repetitions, but the arms are interleaved.

## Result (`summary.json`)

| arm | runs | HashAgg batches | spilled | backend peak RSS | CPU | execution time |
|---|---|---|---|---|---|---|
| buggy | 6 | **199,770** | 99.6 MB | 26.5 MB | 3.46 s (2.72–4.59) | 3,499 ms |
| fixed | 5 | **6,694** | 99.6 MB | 18.3 MB | 2.50 s (2.05–3.60) | 2,571 ms |

Buggy/fixed:
- **batches: 29.8×**;
- peak memory: 1.44× (95% CI 1.42–1.47);
- CPU: 1.44× (1.08–1.79);
- time: 1.42× (1.05–1.79).

The same data is spilled in both arms; the buggy arm cuts it into 30 times as many pieces.

# W1 — explode-for-sort cap (the primary run)

**Site:** `internalQueryMaxScansToExplode = 200` · **Oracle:** O1 (workload continuity)

One `$in` element across the bound. At `|$in| = 200` the planner explodes the `$in` into per-value
index scans and merges them (`SORT_MERGE`); at 201 it gives up and takes a blocking `SORT`.

| `k` | plan | keys examined | median ms |
|---|---|---|---|
| 199 | `LIMIT>FETCH>SORT_MERGE>IXSCAN…` | 218 | 4.62 |
| 200 | same | 219 | ~4.7 |
| **201** | `…SORT` (blocking) | **5 025 001** | **~2 050** |

**22 945× work, 436× latency, for one extra `$in` element.** Full numbers in `report.txt`;
`noise-floor.jsonl` is the 30-repeat baseline establishing that ~0.1 rsd is the measurement floor,
so the cliff is four orders of magnitude above noise.

Orientation: `docs/workload-atlas.md`.
Note that N1 later found **BFA already catches W1** (155×) — see
`../2026-09-16-h2-oracle-coverage/`. W1's lasting
value is not novelty; it is SERVER-14034, which reported this same cliff in 2014 when the limit
was 50, was "fixed" by raising it to 200, and is reachable again at 201.

# W2 — hash-join eligibility bound

**Site:** `internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin = 10000` · **Oracle:** O1

One document across the bound decides `$lookup`'s join algorithm.

| foreign docs | join | docs examined | median ms |
|---|---|---|---|
| 10 000 | `HASH_LOOKUP` | 12 000 | 11.4 |
| **10 001** | `NESTED_LOOP` | **20 004 000** | **2 479.9** |

**1 667× work, 217× latency, 145× CPU — to save 0 MB.** The bound is a *memory* guard, but the
hash table at 10 001 documents is under a megabyte; the guard conditions on document count while
the outcome is governed by cost. Resource accounting in
[`../2026-09-15-w2-resource-cost/`](../../instruments/2026-09-15-w2-resource-cost/README.md).

Same shape as W1 (a resource bound gating a strategy switch, site class 1).

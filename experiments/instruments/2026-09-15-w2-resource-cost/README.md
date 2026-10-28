# I8 — what each join plan costs in CPU and memory, not just time

**Why.** Latency alone hides the trade the heuristic is actually making. `isEligibleForHashJoin()`
is nominally a **memory** guard — it refuses hash join when the foreign collection looks too big to
hash. The honest question is therefore: *how much memory does refusing actually save, and how much
CPU does it spend to save it?*

**Method.** `mongod` run inside a systemd user cgroup with CPU and memory accounting, so cost is
attributed to the server alone and the `mongosh` client's own consumption is excluded. 5 repetitions
per plan; local collection 2 000 documents; foreign collections ~630 KB.

| plan | CPU ms/query | mongod peak MB |
|---|---:|---:|
| foreign=10 000, **hash join** (allowed) | **19.1** | 208.0 |
| foreign=10 001, **nested loop** (refused) | **2 758.4** | 208.0 |
| foreign=10 001, **hash join** (cap raised to 20 000) | **18.1** | 208.0 |

## The finding

**The nested loop costs 145× the CPU. It saves 0 MB.**

The memory the heuristic exists to protect was never at risk. The hash table for 10 001 documents
totalling 630 KB is on the order of 1 MB — and the executor's *own* spill threshold
(`internalQuerySBELookupApproxMemoryUseInBytesBeforeSpill`) is **100 MB**, so this hash table is
~100× below the point where MongoDB would have started spilling anyway.

So the trade is not "memory for CPU". It is **145× CPU for nothing**.

This also refines the bug statement from the latency experiments. The defect is not only that the
wrong plan is chosen — it is that a guard denominated in **document count** is standing in front of
a mechanism already protected by a limit denominated in **bytes**. The two are not the same
currency, and the document-count gate fires long before any memory concern is real.

## Honest limits

- Peak RSS is dominated by the WiredTiger cache (208 MB resident of 8 GB configured), so this
  measurement **cannot resolve a sub-megabyte hash table**. The claim is not "the hash table is
  free"; it is that it is far below both the measurement floor and the executor's own 100 MB spill
  threshold, while the CPU cost imposed is 145×.
- CPU is whole-process, so it includes background activity; with 2 758 ms vs 19 ms that is immaterial.
- Measured at one scale (2 000 local documents). The CPU ratio grows linearly with the local side,
  since nested-loop cost is `local x foreign`.

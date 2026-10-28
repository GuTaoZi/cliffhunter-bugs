# P9 valkey/self-reinforcing-sampling-skew — reproduced, weakly: draining a set costs about 2× the CPU

**Bug.** `hashtableSampleEntries()` (`hashtable.c`) scanned from one random cursor until it had
enough samples. Buckets just after an empty run were therefore picked more often; `SPOP` deletes
them, the empty run grows, and later picks scan more empty buckets. Fixed by 45d03e616421
(2025-05-19), which takes a new random cursor per sampled chain.

**Builds:**

| arm | commit |
|---|---|
| buggy | 8d686dd74fcc, the parent of the fix |
| fixed | 45d03e616421 |

Both are `-O3`.

**Workload** (`run.py`): a fresh server per run. `SADD` 1,000,000 members, then `SPOP` one at a
time (1,000 per round trip) until 100,000 remain. Server CPU is recorded per block of 10,000
pops. There are 3 repetitions, interleaved, plus a drift run. Other experiments and builds were
running on the machine at the same time.

## Result (`summary.json`)

| arm | runs | server CPU for 900,000 pops | wall time | slowest block of 10,000 | peak RSS |
|---|---|---|---|---|---|
| buggy | 4 | 8.49 s (7.11–10.86) | 11.7 s | 204 ms | 56.5 MB |
| fixed | 3 | 4.25 s (3.37–4.97) | 8.5 s | 166 ms | 57.8 MB |

Buggy/fixed CPU averages 2.2×, but the 95% interval is wide and touches 1, from three noisy
pairs. The slowdown did not grow over the drain as the commit describes. The table shrinks
as it empties, which probably resets the skew. **The direction is confirmed; the size of the
effect under this workload is not.** The commit's other trigger, deleting in scan order, was not
tried.

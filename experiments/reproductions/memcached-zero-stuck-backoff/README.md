# P1 memcached/zero-stuck-backoff — reproduced: an idle server burns one full core

**Bug.** `lru_maintainer_thread()` (`items.c`) gives each slab class an adaptive sleep. When a
class had no work, the parent commit grew the sleep with `backoff_juggles[i] += backoff_juggles[i] / 8`.
A backoff of 0 therefore stays 0, the next juggle is always due immediately, and the thread
never sleeps. Fixed by 675d89d784df (2017-05-28, "fix lru thread sleeper more"), which seeds a
zero backoff at `MIN_LRU_MAINTAINER_SLEEP` (1 ms). Diff read at that commit.

**Builds** (`tools/reproduce/build.sh`; GCC 15.3.0, `-O2 -g -std=gnu11 -fcommon`; `-Werror` stripped
because GCC 15 warns where 2017's compiler did not):

| arm | commit |
|---|---|
| buggy | 79e35287df4c, the parent of the fix |
| fixed | 675d89d784df |

**Workload** (`run.py`):
- a fresh server for every run: `-m 64 -t 4 -o modern`;
- 2,000 items over four size classes (100 B to 100 KB);
- 3 s to settle, then **30 s with no client activity**.

CPU and peak memory come from `tools/reproduce/measure.py` (the whole process, all threads). The
maintainer's work counter `lru_maintainer_juggles` is read before and after. There are 5
repetitions with the arm order alternated, plus the buggy arm repeated last as a drift control.

## Result (`summary.json`, from `raw/runs.jsonl`)

| arm | runs | CPU during 30 s idle | juggles per second | peak RSS |
|---|---|---|---|---|
| buggy | 6 | **99.86%** of one core (99.83–99.87) | 214,444 | 61.7 MB |
| fixed | 5 | **0.00%** (all 5 runs) | 5.5 | 61.7 MB |

The idle server does 39,000× more maintenance work, and spends a whole core on it, because a
multiplicative backoff that starts at zero stays at zero. Memory is unaffected. The drift run
(buggy, repeated last) matches the first.

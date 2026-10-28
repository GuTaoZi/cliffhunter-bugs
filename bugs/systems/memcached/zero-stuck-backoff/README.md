# memcached/zero-stuck-backoff

LRU crawler backoff stuck at zero (parent of 675d89d784df vs the fix): idle CPU 99.86% vs 0.00% of a core; RSS equal

- **Upstream:** fixed upstream in 675d89d784df (<https://github.com/memcached/memcached/commit/675d89d784df>)
- **Effect:** cpu, strong: idle server CPU 99.86% vs 0.00% of a core
- **Experiment:** P1, C8, report: [experiments/reproductions/memcached-zero-stuck-backoff/README.md](../../../../experiments/reproductions/memcached-zero-stuck-backoff/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); an otherwise idle machine (the measure is the idle CPU of one core)

**Build:**

```sh
tools/reproduce/build.sh memcached 79e35287df4c
tools/reproduce/build.sh memcached 675d89d784df
```

**Run:**

```sh
python3 bugs/systems/memcached/zero-stuck-backoff/repro/run.py --reps 5 --idle 30
python3 tools/reproduce/summarize.py experiments/reproductions/memcached-zero-stuck-backoff > experiments/reproductions/memcached-zero-stuck-backoff/summary.json
```

**Writes:** data/experiments/memcached-zero-stuck-backoff/raw/runs.jsonl and server.log (replaced), the summary.json

**Minutes:** about 7

**Notes:** Port 15401. fix/ holds the upstream diff for reading; the fixed arm is built from its own commit. Run as a normal user: memcached refuses to run as root without -u.

## The report

Copied from [`experiments/reproductions/memcached-zero-stuck-backoff/README.md`](../../../../experiments/reproductions/memcached-zero-stuck-backoff/README.md).

### P1 memcached/zero-stuck-backoff — reproduced: an idle server burns one full core

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

#### Result (`summary.json`, from `raw/runs.jsonl`)

| arm | runs | CPU during 30 s idle | juggles per second | peak RSS |
|---|---|---|---|---|
| buggy | 6 | **99.86%** of one core (99.83–99.87) | 214,444 | 61.7 MB |
| fixed | 5 | **0.00%** (all 5 runs) | 5.5 | 61.7 MB |

The idle server does 39,000× more maintenance work, and spends a whole core on it, because a
multiplicative backoff that starts at zero stays at zero. Memory is unaffected. The drift run
(buggy, repeated last) matches the first.

## Files

- [`repro/run.py`](repro/run.py)
- [`fix/upstream-memcached-zero-stuck-backoff.diff`](fix/upstream-memcached-zero-stuck-backoff.diff)

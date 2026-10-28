# valkey/self-reinforcing-sampling-skew

Self-reinforcing sampling skew (parent of 45d03e616421 vs the fix): 2.2x CPU, but the 95% interval touches 1: weak

- **Upstream:** fixed upstream in 45d03e616421 (<https://github.com/valkey-io/valkey/commit/45d03e616421> <https://github.com/valkey-io/valkey/pull/2085>)
- **Effect:** cpu, weak: CPU 2.2x, but the 95% interval touches 1
- **Experiment:** P9, report: [experiments/reproductions/valkey-self-reinforcing-sampling-skew/README.md](../../../../experiments/reproductions/valkey-self-reinforcing-sampling-skew/README.md)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** build tools (Nix, or the Ubuntu packages of deps-ubuntu.sh); an idle machine (the effect is 2.2x and its interval nearly touches 1)

**Build:**

```sh
tools/reproduce/build.sh valkey 8d686dd74fcc
tools/reproduce/build.sh valkey 45d03e616421
```

**Run:**

```sh
python3 bugs/systems/valkey/self-reinforcing-sampling-skew/repro/run.py
python3 tools/reproduce/summarize.py experiments/reproductions/valkey-self-reinforcing-sampling-skew > experiments/reproductions/valkey-self-reinforcing-sampling-skew/summary.json
```

**Writes:** data/experiments/valkey-self-reinforcing-sampling-skew/raw/runs.jsonl and server.log (replaced), the summary.json

**Minutes:** about 3

**Notes:** Port 15421. Defaults: 3 repetitions per arm plus a final drift run of the buggy arm.

## The report

Copied from [`experiments/reproductions/valkey-self-reinforcing-sampling-skew/README.md`](../../../../experiments/reproductions/valkey-self-reinforcing-sampling-skew/README.md).

### P9 valkey/self-reinforcing-sampling-skew — reproduced, weakly: draining a set costs about 2× the CPU

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

#### Result (`summary.json`)

| arm | runs | server CPU for 900,000 pops | wall time | slowest block of 10,000 | peak RSS |
|---|---|---|---|---|---|
| buggy | 4 | 8.49 s (7.11–10.86) | 11.7 s | 204 ms | 56.5 MB |
| fixed | 3 | 4.25 s (3.37–4.97) | 8.5 s | 166 ms | 57.8 MB |

Buggy/fixed CPU averages 2.2×, but the 95% interval is wide and touches 1, from three noisy
pairs. The slowdown did not grow over the drain as the commit describes. The table shrinks
as it empties, which probably resets the skew. **The direction is confirmed; the size of the
effect under this workload is not.** The commit's other trigger, deleting in scan order, was not
tried.

## Files

- [`repro/run.py`](repro/run.py)

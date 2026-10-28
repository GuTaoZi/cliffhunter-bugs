# R10 — the knob is a goalpost, measured

**2026-10-01.** Grade: **core**. `mongosh --quiet --port 27117 bugs/systems/mongodb/trial-period/fix/knob_goalpost.js`
and `bugs/systems/mongodb/trial-period/fix/knob_rate.js`. MongoDB 8.2.12, `w4` dataset (3,000,000 documents).

## Why, and what was asked

The plan was to add knobs to MongoDB sites, compare knob-via-eBPF against knob-via-patch, and
measure the optimization rate. **The eBPF arm cannot run in this environment** —
`kernel.unprivileged_bpf_disabled = 2`, `perf_event_paranoid = 2`, uid 1001, and `bpftrace`
from nix fails with *"Missing CAP_DAC_READ_SEARCH capability, please run bpftrace as the root
user."* That is an environment limit, not a finding, and nothing below substitutes for it.

What replaced it is better aimed anyway: MongoDB **already exposes** these constants at runtime
via `setParameter`, with no rebuild. The vendor has done by hand what Xkernel automates for
Linux. So the sharpest available question is not *can we make the constant tunable* but **does
tuning it fix the defect** — asked of a site where the knob already exists.

## First answer, and why it is the wrong question

Measuring the knob against a **fixed** workload:

```
optimization rate = (stock − best knob) / (stock − forced optimum)
```

| knob | docs examined | | 
|---:|---:|---|
| **101** (shipped) | 2,950,000 | |
| 202 | 50,101 | |
| 5050 | 50,101 | |
| forced optimum (`hint({b:1})`) | 50,101 | |

**Optimization rate = 100.0%.** Raising the bound from 101 to 202 lands exactly on what
forcing the right plan achieves. That number is true, it is reproducible, and it is the wrong
question — which the next table shows.

## The right question: the cliff moves, it does not close

The trial fills its batch with matches, so what decides the outcome is the **match count
versus the knob**, and the match count is a property of the data. `w4` ships two collections
that differ only in that: `docs` has 101 matching documents, `docs_k1000` has 1,000.

| knob | `docs` (101 matches) | `docs_k1000` (1,000 matches) |
|---:|---|---|
| **101** (shipped) | **CLIFF** 2,950,000 | **CLIFF** 2,950,000 |
| **202** | ok 50,101 | **CLIFF 2,950,000** |
| 1010 | ok 50,101 | ok 51,000 |
| 5050 | ok 50,101 | ok 51,000 |
| *forced optimum* | *50,101* | *51,000* |

**The setting that fixes one workload leaves the other at full cliff magnitude — 2,950,000
documents against an optimum of 51,000, a factor of 58.** Nothing was shrunk. The threshold
moved, and the workload that sits just past it is still there.

So the same knob scores **100% against a workload fixed in advance and 0% against a workload
chosen after the knob is set.** Both numbers come from the same five lines of `explain`.

## And raising it is not free

Work done *inside* plan selection, summed over all candidates (`allPlansExecution`):

| knob | trial work (documents) | candidates |
|---:|---:|---:|
| 101 | **202** | 3 |
| 202 | **100,254** | 3 |
| 1010 | 100,254 | 3 |
| 5050 | 100,254 | 3 |

**A 496× increase in planning work** to buy a 58× execution saving — and the planning cost is
paid on every new query shape, including every shape the heuristic was already getting right.
It plateaus at 100,254 because past the EOF point each candidate simply runs to completion
(2 × 50,101), so the tax is bounded but immediate: it is incurred in full at the first step
above the default.

## What this establishes

1. **An optimization rate measured against a fixed workload is not evidence a knob works.** It
   is the headroom recovered *for that workload*, and for a threshold heuristic the adversary
   is a workload, not a number. Any knob paper that reports only the fixed-workload number is
   reporting the wrong one — ours would have, which is why this is recorded.
2. **The defect is not in the constant.** The constant's value is a goalpost; the defect is
   that the decision is taken on a prefix at all. This is the same conclusion `docs/studies/main/repair.md`
   reached from eleven other directions, now with a two-column table instead of an argument.
3. **The vendor's own knob is the strongest possible version of the knob remedy** — no rebuild,
   no symbolic execution, officially supported — and it still does not fix the class. That
   bounds what Xkernel-style tunability can buy: making a constant changeable is a different
   problem from the constant being wrong.

## Limits

- **One site, and the metric is why.** `w6` was the intended second site and is **not
  measurable this way**: its defect is a breached memory guard, not a cost cliff, and the run
  is 4.2x *faster* while violating the limit (W6's inverted oracle sign). There is no latency
  headroom and no forced optimum, so "optimization rate" is undefined for it. The metric
  applies to **threshold-shaped** defects only, which is itself a limit on how general a
  knob-effectiveness number can be. The site is left in `bugs/systems/mongodb/trial-period/fix/knob_rate.js`, disabled,
  with the reason.
- **`docsExamined` is the metric, and the reason is measured.** Re-running the same sweep
  after the collection was warm gave a stock wall time of **28 ms instead of 1,441 ms** -- a
  51x swing from cache state alone -- while `docsExamined` stayed at exactly 2,950,000 in both
  runs. Wall time on this site is dominated by whether 3,000,000 documents are resident, not
  by the defect. Both runs are in `rate.txt`; the work counter is the claim and the time is
  context.
- **The adversary is one extra collection**, not a sweep over match counts. The claim is that
  the cliff relocates, which two points establish; how the cliff's magnitude varies with the
  match count is not measured.
- **No eBPF arm.** Blocked by privilege, as above.

## Files

| file | what |
|---|---|
| `goalpost.txt` | the knob × workload matrix |
| `rate.txt` | the fixed-workload sweep and the 100% rate |
| `../../harness/knob_goalpost.js`, `../../harness/knob_rate.js` | the harnesses |

# mongodb/SERVER-107471

SERVER-79039 and SERVER-107471 on master (mongod 9.1, 6d990baca59c), profiled with perf: alternating arrival multi-plans all 1,440 queries (719 replans, server CPU 1.9x on the same 36.0 M documents), the symptom MultiPlanStage::runTrials at 95% of samples vs 1%; the skip query's cached plan makes each selective query read 20,000 documents instead of 1 with 0 replans (8.6x documents, CPU 1.4x), the symptom CachedPlanStage::pickBestPlan at 92% of samples

- **Upstream:** declined upstream (<https://jira.mongodb.org/browse/SERVER-107471>)
- **Effect:** latency, strong: rare queries p50/p99 22.6/38.3 vs 1.9/2.4 ms, server CPU 488.7 vs 294.8 ms per run, peak 2,717.1 vs 2,717.2 MB; the rare query reads 20,000x the documents, by arrival order alone
- **Experiment:** N3, N4, P29, report: [experiments/existing-tools/2026-09-21-jira-repro/README.md](../../../../experiments/existing-tools/2026-09-21-jira-repro/README.md)
- **Side by side with the other MongoDB latency bugs**, with where the time goes and where a timer belongs: [`docs/mongodb-latency-bugs.md`](../../../../docs/mongodb-latency-bugs.md#2-server-107471-a-skip-poisons-the-replan-threshold)

## Run it

Paths are relative to the kit's root. First the set-up of the top README: the build tools (`tools/reproduce/deps-ubuntu.sh` on Ubuntu or Debian, or Nix) and `tools/reproduce/setup.sh`.

**Needs:** mongod 8.2.12 and mongosh 2.9.1 on PATH; systemd-run --user with the cgroup v2 cpu and memory controllers delegated (the start script and the resource pass use them); about 4 GB of free RAM

**Run:**

```sh
CH_PORT=15451 tools/harness/start_mongod_cgroup.sh
cd bugs/systems/mongodb/SERVER-107471/repro
CH_PORT=15451 sh run_s107471.sh my-repro
```

**Writes:** experiments/existing-tools/my-repro/: env.md, raw/s107471_*.log, s107471.jsonl, s107471-report.txt (the summary), s107471-resources.txt (CPU and memory of the server's cgroup)

**Minutes:** about 3

**Notes:** Give the run a new name (my-repro above): 2026-09-21-jira-repro holds the recorded run. Pass the same CH_PORT to both scripts: the resource pass reads it too. If the systemd unit (CH_UNIT, default mongod-ch) is missing, the resource pass exits and its file stays empty. Run from the repro directory, so that the scripts' load() of tools/harness/lib.js resolves. Result sets must stay below 101 documents (the report's threat 4): do not enlarge S1_LIMIT. The premise check is experiments/existing-tools/2026-09-21-jira-repro/probe0_premise.js, run by hand with mongosh.

## The report

Both MongoDB tickets share one report: [`experiments/existing-tools/2026-09-21-jira-repro/README.md`](../../../../experiments/existing-tools/2026-09-21-jira-repro/README.md), with the runs' records, rendered reports and resource costs next to it.

Both were also run on master and profiled with perf: [`experiments/reproductions/mongodb-profiles/README.md`](../../../../experiments/reproductions/mongodb-profiles/README.md) gives the symptom function, its call stack, the deciding code and a step-by-step pipeline.

## Files

- [`discussion.md`](discussion.md): the upstream ticket and its discussion, people named by role
- [`repro/run_s107471.sh`](repro/run_s107471.sh)
- [`repro/s107471_build.js`](repro/s107471_build.js)
- [`repro/s107471_order.js`](repro/s107471_order.js)
- [`repro/s107471_report.py`](repro/s107471_report.py)
- [`repro/s107471_resource_cost.py`](repro/s107471_resource_cost.py)

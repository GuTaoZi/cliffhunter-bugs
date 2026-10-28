# mongodb/SERVER-107471

SERVER-79039 and SERVER-107471 on master (mongod 9.1, 6d990baca59c), profiled with perf: alternating arrival multi-plans all 1,440 queries (719 replans, server CPU 1.9x on the same 36.0 M documents), the symptom MultiPlanStage::runTrials at 95% of samples vs 1%; the skip query's cached plan makes each selective query read 20,000 documents instead of 1 with 0 replans (8.6x documents, CPU 1.4x), the symptom CachedPlanStage::pickBestPlan at 92% of samples

- **Upstream:** declined upstream (<https://jira.mongodb.org/browse/SERVER-107471>)
- **Effect:** latency, strong: server time 1.8x by arrival order alone; the rare query reads 20,000x the documents (wrong cached plan, never replanned)
- **Experiment:** N3, N4, P29, report: [experiments/existing-tools/2026-09-21-jira-repro/README.md](../../../../experiments/existing-tools/2026-09-21-jira-repro/README.md)

## Run it

Paths are relative to the kit's root; `tools/reproduce/setup.sh` first (see the top README).

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

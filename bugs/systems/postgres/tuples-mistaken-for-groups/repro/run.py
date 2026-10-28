#!/usr/bin/env python3
"""postgres/tuples-mistaken-for-groups: buggy parent vs fix, HashAgg spilling recursively.

Bug (src/backend/executor/nodeAgg.c): when a spilled HashAgg partition is spilled again, the
number of tuples in it was used as the estimate of its number of groups, so it was split into far
too many partitions (many tiny batches). Fixed by 9878b643f37b (2020-07-28), which estimates the
partition's group count with HyperLogLog.

Each run: fresh server; one backend runs (via PGOPTIONS: work_mem=64kB, enable_sort=off,
max_parallel_workers_per_gather=0, jit=off)
  EXPLAIN (ANALYZE, FORMAT JSON) SELECT k, count(*) FROM
    (SELECT i % GROUPS AS k FROM generate_series(1, ROWS) i) s GROUP BY k;
under tools/reproduce/measure.py on the postmaster tree. Records HashAgg batches, peak memory and disk usage
from the plan, and execution time. Arms alternate; buggy repeated last.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "reproduce"))
from pg import PG, ROOT, install_dir  # noqa: E402

ARMS = {"buggy": install_dir("9878b643f37~1"), "fixed": install_dir("9878b643f37")}
PORT = 15432


def find(node, key):
    if isinstance(node, dict):
        if key in node:
            yield node
        for v in node.values():
            yield from find(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from find(v, key)


def one(arm, rows, groups):
    pg = PG(ARMS[arm], PORT, f"{ROOT}/pgdata/hashagg-{arm}")
    pg.initdb()
    pg.start()
    try:
        sql = (f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT k, count(*) FROM "
               f"(SELECT i % {groups} AS k FROM generate_series(1,{rows}) i) s GROUP BY k")
        out_f = os.path.join(REPO, "data", "experiments", "postgres-tuples-mistaken-for-groups", "raw", f"plan-{arm}.json")
        env = dict(os.environ, PGOPTIONS="-c work_mem=64kB -c enable_sort=off -c max_parallel_workers_per_gather=0 -c jit=off")
        m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(pg.proc_pid),
                            "--", *pg.psql_cmd(sql), "-o", out_f], capture_output=True, text=True, env=env)
        rec = json.loads(m.stdout.strip().splitlines()[-1])
        if rec.get("workload_exit") != 0:
            raise RuntimeError(m.stderr[-500:])
        plan = json.loads(open(out_f).read())
        agg = next(n for n in find(plan, "Node Type") if n["Node Type"] == "Aggregate")
        rec.update({"arm": arm, "rows": rows, "groups": groups, "batches": agg.get("HashAgg Batches"),
                    "agg_peak_mem_kb": agg.get("Peak Memory Usage"), "agg_disk_kb": agg.get("Disk Usage"),
                    "exec_ms": plan[0]["Execution Time"]})
        return rec
    finally:
        pg.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--rows", type=int, default=4_000_000)
    ap.add_argument("--groups", type=int, default=200_000)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "postgres-tuples-mistaken-for-groups", "raw"), exist_ok=True)
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "postgres-tuples-mistaken-for-groups", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, a.rows, a.groups)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"batches {rec['batches']}", f"disk {rec['agg_disk_kb']} kB", f"mem {rec['agg_peak_mem_kb']} kB",
                  f"exec {rec['exec_ms']:.0f}ms", f"cpu {rec['cpu_s']}s", f"peak {rec['peak_rss_mb']}MB", flush=True)


if __name__ == "__main__":
    main()

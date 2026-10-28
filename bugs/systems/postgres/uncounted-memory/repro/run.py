#!/usr/bin/env python3
"""postgres/uncounted-memory: buggy parent vs fix, a datum sort under work_mem.

Bug (src/backend/utils/sort/tuplesortvariants.c tuplesort_putdatum): with the bump allocator
(unbounded sorts), the memory of a pass-by-reference datum was counted as 0 bytes, so the sort
never saw work_mem exceeded and kept everything in memory. Fixed by 85adc584e2bd (2026-10-06).

Each run: fresh server (shared_buffers 128MB), one backend runs
  (work_mem=WORK_MEM, max_parallel_workers_per_gather=0, jit=off, via PGOPTIONS)
  EXPLAIN (ANALYZE, FORMAT JSON) SELECT repeat(md5(i::text), WIDTH/32) FROM generate_series(1, ROWS) i ORDER BY 1;
The datum must be much wider than the 24-byte SortTuple slot, which IS counted: with narrow datums
(e.g. a bare md5) the slot array alone exceeds work_mem and both arms spill (first attempt, kept in
raw/runs.jsonl).
under tools/reproduce/measure.py on the postmaster tree (CPU of all processes; peak RSS of the largest one,
i.e. the backend). Records the plan's Sort Method, Space Used and Type, and execution time.
Arms alternate; buggy repeated last.
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

ARMS = {"buggy": install_dir("85adc584e2b~1"), "fixed": install_dir("85adc584e2b")}
PORT = 15431


def find(node, key):
    if isinstance(node, dict):
        if key in node:
            yield node
        for v in node.values():
            yield from find(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from find(v, key)


def one(arm, rows, width, work_mem):
    pg = PG(ARMS[arm], PORT, f"{ROOT}/pgdata/uncounted-memory-{arm}")
    pg.initdb()
    pg.start(["-c shared_buffers=128MB"])
    try:
        sql = (f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT repeat(md5(i::text), {width // 32}) "
               f"FROM generate_series(1,{rows}) i ORDER BY 1")
        out_f = os.path.join(REPO, "data", "experiments", "postgres-uncounted-memory", "raw", f"plan-{arm}.json")
        env = dict(os.environ, PGOPTIONS=f"-c work_mem={work_mem} -c max_parallel_workers_per_gather=0 -c jit=off")
        m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(pg.proc_pid),
                            "--", *pg.psql_cmd(sql), "-o", out_f], capture_output=True, text=True, env=env)
        rec = json.loads(m.stdout.strip().splitlines()[-1])
        if rec.get("workload_exit") != 0:
            raise RuntimeError(m.stderr[-500:])
        plan = json.loads(open(out_f).read())
        sortn = next(find(plan, "Sort Method"))
        rec.update({"arm": arm, "rows": rows, "width": width, "work_mem": work_mem, "sort_method": sortn["Sort Method"],
                    "sort_space_kb": sortn.get("Sort Space Used"), "sort_space_type": sortn.get("Sort Space Type"),
                    "exec_ms": plan[0]["Execution Time"]})
        return rec
    finally:
        pg.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--rows", type=int, default=500_000)
    ap.add_argument("--width", type=int, default=1024, help="bytes per sorted datum (multiple of 32)")
    ap.add_argument("--work-mem", default="64MB")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "postgres-uncounted-memory", "raw"), exist_ok=True)
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "postgres-uncounted-memory", "raw", f"runs{a.tag}.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, a.rows, a.width, a.work_mem)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, rec["sort_method"], rec["sort_space_type"], rec["sort_space_kb"], "kB",
                  f"exec {rec['exec_ms']:.0f}ms", f"cpu {rec['cpu_s']}s", f"peak {rec['peak_rss_mb']}MB", flush=True)


if __name__ == "__main__":
    main()

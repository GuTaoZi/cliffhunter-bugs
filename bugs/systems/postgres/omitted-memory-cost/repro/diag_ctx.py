#!/usr/bin/env python3
"""Diagnostic (not a measured run): while the join runs once on an arm, ask the backend every 0.5 s to log its
memory contexts (pg_log_backend_memory_contexts) and report the largest HashSpillContext (the batch files'
BufFiles, each with a BLCKSZ buffer) and HashTableContext seen, from the server log.

  diag_ctx.py --arm NAME=INSTALL:PORT --ds X  [workload.py dataset options]
"""
import re
import subprocess
import sys
import time

sys.argv[0] = "workload.py"
import workload as w  # noqa: E402


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True)
    ap.add_argument("--ds", required=True)
    for opt, d in (("--n-distinct", 200000), ("--n-dup", 100000), ("--n-outer", 600000), ("--dup-key", 0)):
        ap.add_argument(opt, type=int, default=d)
    ap.add_argument("--order", default="dups-last")
    ap.add_argument("--work-mem", default="64kB")
    ap.add_argument("--hash-mem-multiplier", default="2.0")
    ap.add_argument("--timeout-s", type=int, default=900)
    a = ap.parse_args()
    for name, pg in w.parse_arms(a.arm, a.ds):
        pg.start(w.SERVER_OPTS)
        log = pg.data + ".log"
        off = len(open(log, "rb").read())
        q = subprocess.Popen(pg.psql_cmd("SET application_name='diag'; " + w.query_sql(a)), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        polls = 0
        while q.poll() is None:
            try:
                pg.psql("SELECT pg_log_backend_memory_contexts(pid) FROM pg_stat_activity "
                        "WHERE application_name='diag' AND state='active'")
                polls += 1
            except RuntimeError:
                pass
            time.sleep(0.5)
        out = q.communicate()[0]
        time.sleep(0.5)
        txt = open(log, "rb").read()[off:].decode(errors="replace")
        best = {}
        for ctx in ("HashSpillContext", "HashTableContext", "HashBatchContext", "ExecutorState"):
            vals = [(int(m[1]), int(m[2])) for m in re.finditer(ctx + r": (\d+) total in (\d+) blocks", txt)]
            if vals:
                best[ctx] = max(vals)
        ex = w.parse_explain(out)
        print(f"{name}: polls={polls} batches={ex.get('batches')} "
              + " ".join(f"{k}=max {v[0]/2**20:.1f} MB in {v[1]} blocks" for k, v in best.items()), flush=True)
        pg.stop()


if __name__ == "__main__":
    main()

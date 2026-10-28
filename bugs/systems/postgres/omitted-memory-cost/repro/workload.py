#!/usr/bin/env python3
"""Hash join batch explosion: PostgreSQL fix a1b4f289beec ("Consider BufFiles when adjusting hashjoin
parameters") against its parent 8b886a4e3488.

The hashed (inner) table holds N distinct keys plus D copies of one key (0); the probe (outer) table
holds M distinct keys 1..M (none is 0, so the duplicate group never matches and the outer side has
no skew). Tables are VACUUM FREEZEd (row counts known to the planner) but never ANALYZEd, so the
planner does not know about the duplicate group, as in the bug reports. The query is a serial hash
join run as EXPLAIN (ANALYZE, TIMING OFF), so each repetition also yields the batch count.

  workload.py setup   --arm NAME=INSTALL_DIR[:PORT] ...   initdb, start, load (idempotent)
  workload.py run     --arm ... --reps R                    interleaved measured runs -> results.jsonl
  workload.py stop    --arm ...

Each measured run: tools/reproduce/measure.py --pid <postmaster> -- psql -c "<SETs; EXPLAIN ANALYZE ...>"
(wall, CPU of the postmaster tree, peak VmHWM of any process in it), plus a sampler of the largest
RssAnon (private memory) of any process in the tree, plus the pg_stat_database temp_files/temp_bytes
delta for the run.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time

TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../tools/reproduce"))
sys.path.insert(0, TOOLS)
from pg import PG  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_OPTS = ["-c autovacuum=off", "-c shared_buffers=128MB", "-c max_parallel_workers_per_gather=0",
               "-c max_parallel_workers=0", "-c jit=off", "-c log_temp_files=-1"]


def parse_arms(specs, ds):
    arms = []
    for i, s in enumerate(specs):
        name, rest = s.split("=", 1)
        inst, _, port = rest.partition(":")
        port = int(port) if port else 15420 + i
        assert 15420 <= port <= 15429, port
        # short data paths: the Unix socket path (datadir + ".sock/.s.PGSQL.port") must stay under 107 bytes
        arms.append((name, PG(inst, port, f"{HERE}/d/{name}{ds}")))
    return arms


def query_sql(a):
    hm = "" if a.hash_mem_multiplier == "none" else f"SET hash_mem_multiplier={a.hash_mem_multiplier}; "
    sets = (f"SET work_mem='{a.work_mem}'; {hm}"
            "SET enable_mergejoin=off; SET enable_nestloop=off; SET max_parallel_workers_per_gather=0; "
            f"SET statement_timeout='{a.timeout_s}s'; ")
    return sets + ("EXPLAIN (ANALYZE, TIMING OFF, COSTS OFF, SUMMARY ON) "
                   "SELECT count(*) FROM outer_t o JOIN inner_t i ON o.k = i.k;")


def setup(a, arms):
    # physical order of the hashed table: distinct keys (ascending) then the duplicate group, the reverse, or random
    order = {"dups-last": f"ORDER BY (k = {a.dup_key}), k", "dups-first": f"ORDER BY (k <> {a.dup_key}), k",
             "shuffled": "ORDER BY random()"}[a.order]
    for name, pg in arms:
        pf = pg.data + ".params.json"
        want = dict(n_distinct=a.n_distinct, n_dup=a.n_dup, n_outer=a.n_outer, order=a.order, dup_key=a.dup_key)
        if os.path.exists(pf):
            assert json.load(open(pf)) == want, f"dataset {a.ds} was loaded with other parameters: {open(pf).read()}"
        pg.initdb()
        try:
            pg.stop()
        except Exception:
            pass
        pg.start(SERVER_OPTS)
        have = pg.psql("SELECT count(*) FROM pg_class WHERE relname IN ('inner_t','outer_t')").strip()
        if have != "2":
            pg.psql("SELECT setseed(0.42)")
            pg.psql("DROP TABLE IF EXISTS inner_t, outer_t; CREATE TABLE inner_t(k int); CREATE TABLE outer_t(k int);"
                    "ALTER TABLE inner_t SET (autovacuum_enabled=off); ALTER TABLE outer_t SET (autovacuum_enabled=off);")
            pg.psql(f"SELECT setseed(0.42); INSERT INTO inner_t SELECT k FROM ("
                    f"SELECT g AS k FROM generate_series(1,{a.n_distinct}) g UNION ALL "
                    f"SELECT {a.dup_key} FROM generate_series(1,{a.n_dup})) s {order};")
            pg.psql(f"INSERT INTO outer_t SELECT g FROM generate_series(1,{a.n_outer}) g;")
            pg.psql("VACUUM (FREEZE) inner_t;")
            pg.psql("VACUUM (FREEZE) outer_t;")
            json.dump(want, open(pf, "w"))
        cnt = pg.psql(f"SELECT (SELECT count(*) FROM inner_t), (SELECT count(*) FROM inner_t WHERE k={a.dup_key}), "
                      "(SELECT count(*) FROM outer_t), (SELECT count(*) FROM pg_stats WHERE tablename IN ('inner_t','outer_t'))")
        print(f"{name}: port {pg.port} pid {pg.proc_pid} rows inner|dup|outer|stats = {cnt.strip()}", flush=True)
        plan = pg.psql(query_sql(a).replace("ANALYZE, TIMING OFF, COSTS OFF, SUMMARY ON", "COSTS ON"))
        print(plan, flush=True)


class AnonSampler(threading.Thread):
    """Largest RssAnon (private, anonymous memory) of any process in the postmaster's tree."""

    def __init__(self, root):
        super().__init__(daemon=True)
        self.root, self.stop, self.peak_kb, self.peak_pid = root, threading.Event(), 0, None

    def tree(self, pid):
        out = [pid]
        try:
            for k in open(f"/proc/{pid}/task/{pid}/children").read().split():
                out += self.tree(int(k))
        except OSError:
            pass
        return out

    def run(self):
        while not self.stop.is_set():
            for p in self.tree(self.root):
                try:
                    for ln in open(f"/proc/{p}/status"):
                        if ln.startswith("RssAnon:"):
                            v = int(ln.split()[1])
                            if v > self.peak_kb:
                                self.peak_kb, self.peak_pid = v, p
                            break
                except OSError:
                    pass
            self.stop.wait(0.02)


def temp_stats(pg):
    r = pg.psql("SELECT temp_files, temp_bytes FROM pg_stat_database WHERE datname='postgres'").strip().split("|")
    return int(r[0]), int(r[1])


def parse_explain(txt):
    out = {}
    m = re.search(r"Buckets: (\d+)(?: \(originally (\d+)\))?\s+Batches: (\d+)(?: \(originally (\d+)\))?\s+"
                  r"Memory Usage: (\d+)kB", txt)
    if m:
        out.update(buckets=int(m[1]), buckets_orig=int(m[2] or m[1]), batches=int(m[3]),
                   batches_orig=int(m[4] or m[3]), hash_mem_usage_kb=int(m[5]))
    m = re.search(r"Execution Time: ([\d.]+) ms", txt)
    if m:
        out["exec_ms"] = float(m[1])
    m = re.search(r"Hash Join \(actual rows=(\d+)", txt)
    if m:
        out["join_rows"] = int(m[1])
    m = re.search(r"Hash \(actual rows=(\d+)", txt)
    if m:
        out["hash_rows"] = int(m[1])
    m = re.search(r"Hash Cond: \((\S+) = (\S+)\)", txt)
    if m:
        out["hash_cond"] = f"{m[1]} = {m[2]}"
    m = re.search(r"->  Seq Scan on (\w+) \w+ \(actual[^\n]*\n\s*->  Hash", txt)
    if m:
        out["probe_rel"] = m[1]
    return out


def one_run(a, name, pg, rep, logf):
    tf0, tb0 = temp_stats(pg)
    s = AnonSampler(pg.proc_pid)
    s.start()
    cmd = [sys.executable, f"{TOOLS}/measure.py", "--pid", str(pg.proc_pid), "--"] + pg.psql_cmd(query_sql(a))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout_s + 120)
    s.stop.set()
    s.join(timeout=2)
    lines = r.stdout.strip().splitlines()
    meas = json.loads(lines[-1])
    explain = "\n".join(lines[:-1])
    time.sleep(1.0)                      # let the backend exit and flush its statistics
    tf1, tb1 = temp_stats(pg)
    rec = dict(arm=name, rep=rep, port=pg.port, **meas, peak_rss_anon_mb=round(s.peak_kb / 1024, 1),
               temp_files=tf1 - tf0, temp_mb=round((tb1 - tb0) / 2**20, 1), **parse_explain(explain),
               stderr=r.stderr.strip()[-300:], params=dict(n_distinct=a.n_distinct, n_dup=a.n_dup, n_outer=a.n_outer,
                                                           work_mem=a.work_mem, order=a.order, dup_key=a.dup_key,
                                                           tag=a.tag))
    logf.write(f"===== {name} rep {rep}\n{explain}\n{r.stderr}\n")
    logf.flush()
    return rec


def run(a, arms):
    for _, pg in arms:
        pg.proc_pid = int(open(os.path.join(pg.data, "postmaster.pid")).readline())
    os.makedirs(f"{HERE}/results", exist_ok=True)
    out = open(f"{HERE}/results/{a.tag}.jsonl", "a")
    logf = open(f"{HERE}/logs/{a.tag}.explain.log", "a")
    if a.warmup:
        for name, pg in arms:
            rec = one_run(a, name, pg, -1, logf)
            print("warmup", json.dumps(rec), flush=True)
    for rep in range(a.reps):
        seq = arms if rep % 2 == 0 else arms[::-1]       # interleaved, alternating order
        for name, pg in seq:
            rec = one_run(a, name, pg, rep, logf)
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(json.dumps(rec), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["setup", "run", "stop"])
    ap.add_argument("--arm", action="append", required=True, help="NAME=INSTALL_DIR[:PORT]")
    ap.add_argument("--n-distinct", type=int, default=200000)
    ap.add_argument("--n-dup", type=int, default=100000)
    ap.add_argument("--n-outer", type=int, default=600000)
    ap.add_argument("--dup-key", type=int, default=0,
                    help="the repeated key; -57267 has hashint4 = 698 (bits 10-31 zero), so it stays in batch 0")
    ap.add_argument("--order", default="dups-last", choices=["shuffled", "dups-last", "dups-first"])
    ap.add_argument("--work-mem", default="64kB")
    ap.add_argument("--hash-mem-multiplier", default="2.0")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--warmup", action="store_true")
    ap.add_argument("--tag", default="main")
    ap.add_argument("--ds", default="1", help="short dataset id (data dir suffix); its parameters are recorded")
    a = ap.parse_args()
    arms = parse_arms(a.arm, a.ds)
    if a.action == "setup":
        setup(a, arms)
    elif a.action == "run":
        run(a, arms)
    else:
        for _, pg in arms:
            pg.stop()


if __name__ == "__main__":
    main()

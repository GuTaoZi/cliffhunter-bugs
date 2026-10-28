#!/usr/bin/env python3
"""postgres/decay-outruns-growth (queue rank 20): read-stream look-ahead decays per hit faster than it grows per miss.

Bug (src/backend/storage/aio/read_stream.c at cceb1bf45e3a): the look-ahead distance doubles only after waiting for a
read (952-955) and drops by one for every buffer hit that needed no I/O (365-370). A scan whose uncached blocks are
separated by cached ones therefore stays at distance 1 or 2: at most one read is in flight and every miss is waited
for at once, so the scan runs at the device's queue-depth-1 latency however much I/O concurrency is configured.
Fixed upstream in 6e36930f9aaf (2026-04-01): after each wait, decay is held off for max_pinned_buffers hits
(distance_decay_holdoff, 366-384, 984), and it never decays while reads are in flight. Parent cceb1bf45e3a. Same
catalog version, so both arms run on one data directory.

Data: table t(id, m, pad) with one row per 8 kB block (a 5,000-byte uncompressed pad), block = id, m = id % STRIDE,
an index on m, frozen. STRIDE is 64: calibrate_stride showed that this disk (or its controller, or the kernel's
read-ahead) serves one block in every 2 as fast at queue depth 1 as at 16 (0.10 ms per read), so there the look-ahead
cannot matter, while one block in every 64 costs 3.2 ms per read at depth 1 and 1.2 ms at depth 16. A first version
with STRIDE 2 is kept in data/first-version-stride-2/. One run (fresh server per run):
  1. server stopped; the table's files fsynced and dropped from the OS page cache (POSIX_FADV_DONTNEED), checked
     with fincore;
  2. start the arm's binary (shared_buffers 16GB, io_method worker, 16 io workers, effective_io_concurrency EIC:
     16, the default, or 64, whose look-ahead window of (EIC + 1) x 16 blocks spans 16 misses at STRIDE 64); read
     the blocks with m > 0 into shared buffers with a bitmap heap scan, then drop the OS cache again: 63 blocks in
     every 64 are now buffer hits and the 64th a device read;
  3. measured: one sequential scan of the whole table, EXPLAIN (ANALYZE, BUFFERS) (shared hit and read counts
     checked), its wall time, and the server's CPU (postmaster and all children, io workers included) and peak RSS
     (tools/reproduce/measure.py's Sampler).
MODE=allcold skips step 2's warm-up (every block a read, so the distance grows in both arms): the control.
calibrate measures this disk's queue-depth-1 8 kB random-read latency and the row count it implies for a ~20 s
parent scan. Arms alternate per repetition.

    run.py calibrate | calibrate_stride | setup [N] | measure [REPS] [MODE] | report
"""
import glob
import json
import os
import random
import re
import statistics as st
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
sys.path.insert(0, f"{REPO}/tools/reproduce")
from measure import Sampler  # noqa: E402
from pg import PG  # noqa: E402

ARMS = {"parent": "cceb1bf45e3a", "fix": "6e36930f9aaf"}
PORT = 15453
DATA = f"{ROOT}/pgdata/decay-outruns-growth/data"
STRIDE = int(os.environ.get("STRIDE", 64))
EIC = int(os.environ.get("EIC", 16))
SETTINGS = ["-c shared_buffers=16GB", "-c max_connections=20", "-c io_method=worker", "-c io_workers=16",
            f"-c effective_io_concurrency={EIC}", "-c autovacuum=off", "-c checkpoint_timeout=1h",
            "-c max_wal_size=16GB", "-c track_io_timing=on"]
SESSION = "SET max_parallel_workers_per_gather=0; SET jit=off; SET synchronize_seqscans=off; "


def pg(arm):
    return PG(f"{ROOT}/build/postgres-{ARMS[arm]}/install", PORT, DATA)


def drop_cache(paths):
    for p in paths:
        fd = os.open(p, os.O_RDONLY)
        try:
            os.fsync(fd)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)


def resident_pages(paths):
    n = 0
    for p in paths:
        out = subprocess.run(["fincore", "-n", "-b", "-o", "RES", p], capture_output=True, text=True).stdout.split()
        n += int(out[0]) // 4096 if out else 0
    return n


def table_files():
    rel = json.load(open(f"{D}/data/table.json"))["relpath"]
    base = os.path.join(DATA, rel)
    return [base] + sorted(glob.glob(base + ".[0-9]*"))


def calibrate():
    path = f"{ROOT}/pgdata/decay-outruns-growth/calib.bin"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    size = 1 << 30
    if not os.path.exists(path) or os.path.getsize(path) != size:
        with open(path, "wb") as f:
            for _ in range(size >> 24):
                f.write(os.urandom(1 << 24))
    drop_cache([path])
    fd = os.open(path, os.O_RDONLY)
    blocks = random.Random(1).sample(range(1, size // 8192, 2), 400)
    lat = []
    for b in blocks:
        t0 = time.perf_counter()
        os.pread(fd, 8192, b * 8192)
        lat.append(time.perf_counter() - t0)
    os.close(fd)
    lat.sort()
    l1 = st.median(lat)
    cold = int(min(200_000, max(20_000, 20.0 / (l1 + 30e-6))))
    rec = {"qd1_read_ms_p50": round(l1 * 1e3, 4), "qd1_read_ms_p90": round(lat[int(0.9 * len(lat))] * 1e3, 4),
           "qd1_read_ms_max": round(lat[-1] * 1e3, 4), "suggested_cold_blocks": cold, "suggested_N": 2 * cold}
    os.makedirs(f"{D}/data", exist_ok=True)
    json.dump(rec, open(f"{D}/data/calibrate.json", "w"))
    print(json.dumps(rec))


def calibrate_stride():
    """Per-read time of 8 kB reads one block in every STRIDE, in file order, at queue depth 1 and 16 (threads), after
    dropping the page cache: whether this device rewards the look-ahead the fix keeps (it does not when read-ahead in
    the kernel or the controller already serves the pattern)."""
    from concurrent.futures import ThreadPoolExecutor
    path = f"{ROOT}/pgdata/decay-outruns-growth/calib.bin"
    size = os.path.getsize(path)
    out = []
    for stride in (2, 16, 64):
        for qd in (1, 16):
            drop_cache([path])
            n = min(2000, size // 8192 // stride)
            offs = [(1 + i * stride) * 8192 for i in range(n)]
            fd = os.open(path, os.O_RDONLY)
            t0 = time.perf_counter()
            if qd == 1:
                for o in offs:
                    os.pread(fd, 8192, o)
            else:
                with ThreadPoolExecutor(qd) as ex:
                    list(ex.map(lambda o: os.pread(fd, 8192, o), offs))
            dt = time.perf_counter() - t0
            os.close(fd)
            out.append({"stride_blocks": stride, "qd": qd, "reads": n, "ms_per_read": round(dt * 1e3 / n, 4)})
            print(json.dumps(out[-1]), flush=True)
    json.dump(out, open(f"{D}/data/calibrate-stride.json", "w"))


def setup(n):
    p = pg("parent")
    p.initdb()
    p.start(SETTINGS)
    try:
        p.psql("DROP TABLE IF EXISTS t")
        p.psql("CREATE TABLE t(id int, m int, pad text); ALTER TABLE t ALTER COLUMN pad SET STORAGE PLAIN")
        p.psql(f"INSERT INTO t SELECT g, g % {STRIDE}, repeat('x', 5000) FROM generate_series(0, {n - 1}) g")
        p.psql("CREATE INDEX ON t(m)")
        p.psql("VACUUM (FREEZE, ANALYZE) t")
        p.psql("CHECKPOINT")
        size = int(p.psql("SELECT pg_relation_size('t')"))
        rel = p.psql("SELECT pg_relation_filepath('t')").strip()
        assert size == n * 8192, (size, n)
        json.dump({"N": n, "stride": STRIDE, "bytes": size, "relpath": rel}, open(f"{D}/data/table.json", "w"))
        print({"N": n, "stride": STRIDE, "bytes": size, "relpath": rel})
    finally:
        p.stop()


def explain_buffers(txt):
    m = re.search(r"Buffers: shared(?: hit=(\d+))?(?: read=(\d+))?", txt)
    ex = re.search(r"Execution Time: ([\d.]+) ms", txt)
    plan = txt.strip().splitlines()[0] if txt.strip() else ""
    return {"hit": int(m.group(1) or 0) if m else None, "read": int(m.group(2) or 0) if m else None,
            "exec_ms": float(ex.group(1)) if ex else None, "plan": plan[:80]}


def one(arm, rep, mode):
    tab = json.load(open(f"{D}/data/table.json"))
    files = table_files()
    p = pg(arm)
    drop_cache(files)
    res0 = resident_pages(files)
    p.start(SETTINGS)
    try:
        warm = None
        if mode == "warm":
            q = (SESSION + "SET enable_seqscan=off; SET enable_indexscan=off; SET enable_indexonlyscan=off; "
                 "EXPLAIN (ANALYZE, BUFFERS, TIMING OFF) SELECT sum(length(pad)) FROM t WHERE m > 0")
            warm = explain_buffers(p.psql(q))
            assert "Bitmap" in p.psql("SET enable_seqscan=off; SET enable_indexscan=off; "
                                      "EXPLAIN SELECT sum(length(pad)) FROM t WHERE m > 0"), "not a bitmap scan"
        drop_cache(files)
        res1 = resident_pages(files)
        smp = Sampler(p.proc_pid)
        for c in [p.proc_pid] + smp_children(p.proc_pid):
            try:
                open(f"/proc/{c}/clear_refs", "w").write("5")
            except OSError:
                pass
        smp.poll()
        smp.start()
        t0 = time.perf_counter()
        txt = p.psql(SESSION + "EXPLAIN (ANALYZE, BUFFERS, TIMING OFF) SELECT count(*), sum(length(pad)) FROM t")
        wall = time.perf_counter() - t0
        smp.stop.set()
        smp.join()
        smp.poll()
        scan = explain_buffers(txt)
        cold = tab["N"] // tab["stride"] if mode == "warm" else tab["N"]
        return {"arm": arm, "sha": ARMS[arm], "rep": rep, "mode": mode, "N": tab["N"], "stride": tab["stride"],
                "eic": EIC, "scan_wall_s": round(wall, 3),
                "scan_exec_ms": scan["exec_ms"], "scan_hit": scan["hit"], "scan_read": scan["read"],
                "scan_plan": scan["plan"], "read_per_cold_block_ms": round(wall * 1e3 / cold, 4),
                "resident_pages_start": res0, "resident_pages_before_scan": res1, "warm": warm,
                "server_cpu_s": round(smp.cpu_s(), 3), "server_peak_rss_mb": round(smp.peak / 1024, 1)}
    finally:
        p.stop()


def smp_children(pid):
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    return [int(x) for x in out]


SHOW = ("arm", "mode", "eic", "rep", "scan_wall_s", "scan_hit", "scan_read", "read_per_cold_block_ms",
        "resident_pages_before_scan", "server_cpu_s", "server_peak_rss_mb")


def measure(reps, mode):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, mode)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in SHOW}), flush=True)


def table(rows, keys):
    out = ["| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [float(r[k]) for r in rows if r["arm"] == arm and r.get(k) is not None]
            means[arm] = st.mean(v) if v else None
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})"
                         if v else "n/a")
        ratio = f"{means['parent'] / means['fix']:.2f}" if means["parent"] is not None and means["fix"] else ""
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    cal = json.load(open(f"{D}/data/calibrate.json")) if os.path.exists(f"{D}/data/calibrate.json") else {}
    keys = ["scan_wall_s", "scan_exec_ms", "read_per_cold_block_ms", "scan_hit", "scan_read",
            "resident_pages_before_scan", "server_cpu_s", "server_peak_rss_mb"]
    out = [f"# postgres decay-outruns-growth: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"One sequential scan of a {rows[0]['N']:,}-block table (one row per block) on disk, io_method worker with 16 "
           "io workers, shared_buffers 16GB. warm: 63 blocks in every 64 in shared buffers and the 64th dropped from "
           "the OS cache, so each device read follows 63 hits; allcold (control): every block a device read. This "
           f"disk's queue-depth-1 8 kB random read: {cal.get('qd1_read_ms_p50')} ms median. "
           "read_per_cold_block_ms: scan wall time per device-read block. mean, sd [min, max]."]
    for mode in ("warm", "allcold"):
        for eic in sorted({r.get("eic", 16) for r in rows}):
            sub = [r for r in rows if r["mode"] == mode and r.get("eic", 16) == eic]
            if sub:
                out += ["", f"## {mode}, effective_io_concurrency {eic}", ""] + table(sub, keys)
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv
    {"calibrate": calibrate, "calibrate_stride": calibrate_stride, "setup": lambda: setup(int(a[2]) if len(a) > 2 else 40_000),
     "measure": lambda: measure(int(a[2]) if len(a) > 2 else 5, a[3] if len(a) > 3 else "warm"),
     "report": report}[a[1]]()

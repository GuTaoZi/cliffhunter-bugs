#!/usr/bin/env python3
"""postgres/gave-up-advising-early (queue rank 70): a read stream advises only the first read after each jump.

Bug (src/backend/storage/aio/read_stream.c at 11bd8318602f): a started read gets READ_BUFFERS_ISSUE_ADVICE
(posix_fadvise WILLNEED, the kernel starts the I/O early) only when it is not sequential with the end of the last read
that had to wait: !suppress_advice && advice_enabled && pending_read_blocknum != seq_blocknum (269-272; seq_blocknum
updated per started read, 334). In a dense run of blocks after a jump, only the first io_combine_limit-sized read (16
blocks) is advised; the run's later chunks are read synchronously when the consumer reaches them. VACUUM's stream is
exactly that: dense runs of pages it must scan, separated by all-visible gaps of at least 32 blocks that it skips
(vacuumlazy.c:1229, 1557, SKIP_PAGES_THRESHOLD 209, 1609). Fixed in 7ea8cd15661e (2025-03-15, "Improve read_stream.c
advice for dense streams."): seq_until_processed keeps advice on for the sequential reads of a run until the consumer
reaches its first I/O (277-289, 879-881). Parent 11bd8318602f; one data directory serves both (same catalog version).
Design: data/agents/prompts/34 (reply in raw/design.md).

Tables of 400,000 blocks, one row per 8 kB block (a 5,000-byte plain pad), frozen, then in a prepared transaction
that is never resolved the rows of a run of R blocks in every 400 deleted, so VACUUM must scan the runs and can never
prune or set them all-visible: each VACUUM is read-only and repeatable. t48: runs of 48 blocks (3 chunks), the
trigger; t16: runs of 16 (one chunk, advised in both arms), a control. One run: the table's files dropped from the
page cache (fsync, POSIX_FADV_DONTNEED; fincore checks), the arm's server started (shared_buffers 512MB, autovacuum off,
track_io_timing on), VACUUM (VERBOSE) timed, the server's CPU and peak RSS (tools/reproduce/measure.py Sampler), the
read time it reports, the device's sectors read (/sys/block/sda/stat) and the table's resident pages after. Control
mic0: t48 with maintenance_io_concurrency 0 (no advice in either arm). Arms alternate per repetition.

    run.py setup | measure TABLE REPS [mic0] | report
"""
import glob
import json
import os
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

ARMS = {"parent": "11bd8318602f", "fix": "7ea8cd15661e"}
PORT = 15478
DATA = f"{ROOT}/pgdata/gave-up-advising-early/data"
N, PERIOD, RUNS = 400_000, 400, {"t48": 48, "t16": 16}
SETTINGS = ["-c shared_buffers=512MB", "-c max_connections=20", "-c max_prepared_transactions=8", "-c autovacuum=off",
            "-c track_io_timing=on", "-c checkpoint_timeout=1h", "-c max_wal_size=32GB"]


def pg(arm):
    return PG(f"{ROOT}/build/postgres-{ARMS[arm]}/install", PORT, DATA)


def psql_all(p, sql):
    r = subprocess.run([f"{p.bin}/psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", p.sock, "-p", str(p.port), "-U",
                        "postgres", "-d", "postgres", "-At", "-c", sql], capture_output=True, text=True, timeout=7200)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout, r.stderr


def files(p, table):
    rel = psql_all(p, f"SELECT pg_relation_filepath('{table}')")[0].strip()
    base = os.path.join(DATA, rel)
    return [x for x in [base] + sorted(glob.glob(base + ".[0-9]*")) + [base + "_vm", base + "_fsm"] if os.path.exists(x)]


def drop_cache(paths):
    for f in paths:
        fd = os.open(f, os.O_RDONLY)
        try:
            os.fsync(fd)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)


def resident(paths):
    n = 0
    for f in paths:
        out = subprocess.run(["fincore", "-n", "-b", "-o", "RES", f], capture_output=True, text=True).stdout.split()
        n += int(out[0]) // 4096 if out else 0
    return n


def sectors_read():
    try:
        return int(open("/sys/block/sda/stat").read().split()[2])
    except (OSError, IndexError, ValueError):
        return None


def setup():
    p = pg("parent")
    p.initdb()
    p.start(SETTINGS)
    try:
        for t, run in RUNS.items():
            psql_all(p, f"DROP TABLE IF EXISTS {t}; CREATE TABLE {t}(id int, pad text); "
                        f"ALTER TABLE {t} ALTER COLUMN pad SET STORAGE PLAIN; "
                        f"INSERT INTO {t} SELECT g, repeat('x', 5000) FROM generate_series(0, {N - 1}) g;")
            psql_all(p, f"VACUUM (FREEZE) {t}")       # its own call: VACUUM cannot run inside a transaction block
        psql_all(p, "CHECKPOINT")
        dels = "; ".join(f"DELETE FROM {t} WHERE id % {PERIOD} < {run}" for t, run in RUNS.items())
        psql_all(p, f"BEGIN; {dels}; PREPARE TRANSACTION 'hold';")
        psql_all(p, "CHECKPOINT")
        info = {t: {"size": int(psql_all(p, f"SELECT pg_relation_size('{t}')")[0]),
                    "last_ctid": psql_all(p, f"SELECT ctid FROM {t} WHERE id = {N - 1}")[0].strip()} for t in RUNS}
        info["prepared"] = int(psql_all(p, "SELECT count(*) FROM pg_prepared_xacts")[0])
    finally:
        p.stop()
    subprocess.run(["sync", "-f", DATA])
    os.makedirs(f"{D}/data", exist_ok=True)
    json.dump(info, open(f"{D}/data/setup.json", "w"), indent=1)
    print(json.dumps(info))


def verbose(err):
    out = {}
    m = re.search(r"pages: (\d+) removed, (\d+) remain, (\d+) scanned", err)
    if m:
        out["pages_scanned"] = int(m.group(3))
    m = re.search(r"I/O timings: read: ([\d.]+) ms", err)
    if m:
        out["io_read_ms"] = float(m.group(1))
    m = re.search(r"avg read rate: ([\d.]+) MB/s", err)
    if m:
        out["read_mb_s"] = float(m.group(1))
    m = re.search(r"buffer usage: (\d+) hits, (\d+) (?:misses|reads)", err)
    if m:
        out["buf_hits"], out["buf_misses"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"elapsed: ([\d.]+) s", err)
    if m:
        out["vacuum_elapsed_s"] = float(m.group(1))
    out["dirtied_zero"] = bool(re.search(r"\b0 dirtied\b", err))
    return out


def one(arm, table, rep, mic0):
    p = pg(arm)
    extra = SETTINGS + (["-c maintenance_io_concurrency=0"] if mic0 else [])
    p.start(extra)
    try:
        fs = files(p, table)
        assert int(psql_all(p, "SELECT count(*) FROM pg_prepared_xacts")[0]) == 1, "the prepared transaction is gone"
    finally:
        p.stop()
    drop_cache(fs)
    res0 = resident(fs)
    p.start(extra)
    try:
        psql_all(p, "SELECT count(*) FROM pg_class")
        sec0 = sectors_read()
        smp = Sampler(p.proc_pid)
        smp.poll()
        smp.start()
        t0 = time.perf_counter()
        _, err = psql_all(p, f"VACUUM (VERBOSE) {table}")
        wall = time.perf_counter() - t0
        smp.stop.set()
        smp.join()
        smp.poll()
        sec1 = sectors_read()
        tag = f"{table}{'-mic0' if mic0 else ''}-{arm}-r{rep}"
        open(f"{D}/data/{tag}.vacuum.txt", "w").write(err)
        row = {"arm": arm, "sha": ARMS[arm], "table": table, "mic0": mic0, "rep": rep, "vacuum_wall_s": round(wall, 3),
               "resident_pages_before": res0, "resident_pages_after": resident(fs),
               "device_mb_read": round((sec1 - sec0) * 512 / 2**20, 1) if sec0 is not None else None,
               "server_cpu_s": round(smp.cpu_s(), 3), "server_peak_rss_mb": round(smp.peak / 1024, 1)}
        row.update(verbose(err))
        return row
    finally:
        p.stop()


SHOW = ("arm", "table", "mic0", "rep", "vacuum_wall_s", "io_read_ms", "pages_scanned", "device_mb_read",
        "resident_pages_before", "resident_pages_after", "server_cpu_s", "server_peak_rss_mb", "dirtied_zero")


def measure(table, reps, mic0=False):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, table, rep, mic0)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in SHOW}), flush=True)


def table_md(rows, keys):
    out = ["| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [float(r[k]) for r in rows if r["arm"] == arm and r.get(k) is not None]
            if not v:
                cells.append("n/a")
                means[arm] = None
                continue
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = (f"{means['parent'] / means['fix']:.2f}" if means["parent"] is not None and means["fix"] else "")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = ["vacuum_wall_s", "vacuum_elapsed_s", "io_read_ms", "read_mb_s", "pages_scanned", "device_mb_read",
            "resident_pages_after", "server_cpu_s", "server_peak_rss_mb"]
    out = [f"# postgres gave-up-advising-early: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"Cold VACUUM (VERBOSE) of a {N:,}-block table whose non-skippable pages are runs of R blocks in every "
           f"{PERIOD} (held by a prepared transaction, so the scan is read-only). io_read_ms: VACUUM's reported read "
           "time; device_mb_read: the disk's sectors read during the VACUUM; resident_pages_after: the table's 4 kB "
           "pages in the page cache after it. mean, sd [min, max].", ""]
    for table, mic0, name in (("t48", False, "t48: runs of 48 blocks (the trigger)"),
                              ("t16", False, "t16: runs of 16 blocks (control: one chunk per run)"),
                              ("t48", True, "t48 with maintenance_io_concurrency 0 (control: no advice)")):
        rs = [r for r in rows if r["table"] == table and r["mic0"] == mic0]
        if rs:
            out += [f"## {name}", ""] + table_md(rs, keys) + [""]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "setup":
        setup()
    elif a[0] == "measure":
        measure(a[1], int(a[2]), len(a) > 3 and a[3] == "mic0")
    else:
        report()

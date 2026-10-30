#!/usr/bin/env python3
"""SERVER-56274: an index seek past the last visible key walks every invisible entry, twice, without cursor bounds.

Without bounds (r7.0.45, b345c2303bcb), an index seek is WiredTiger's search_near (src/mongo/db/storage/wiredtiger/
wiredtiger_index.cpp:1176-1193): when no key at or after the seek key is visible to the reader, search_near steps
next over every invisible entry to the end of the tree, then back with prev (src/third_party/wiredtiger/src/btree/
bt_cursor.c:873-905), and the server's SERVER-56839 loop then advances with next again (wiredtiger_index.cpp:
1225-1236): a seek costs about twice the run of invisible entries. With bounds (SERVER-65528, -65527, -68380 and the
record-store seek of SERVER-85261, all in 8.0; r8.2.12, 10d50f5046de, wiredtiger_index.cpp:968-1006), WiredTiger
positions from the bound and stops at the end of the tree. There is no switch in one binary (SERVER-55750 is an
unrelated flag), so the arms are the two official release binaries, 7.0.45 and 8.2.12, run the same way (the Ubuntu
tarballs through Nix's glibc loader with OpenSSL 3 and curl); WiredTiger's page skipping (WT-10807) is in both.
Design: data/agents/prompts/35 (reply in raw/design.md).

One run: a fresh single-node replica set (pinned to CPUs 0-7, 2 GB cache, transactionLifetimeLimitSeconds 3600),
1,000 documents _id 1..1000, a snapshot transaction opened and its read timestamp pinned by a find, then 1,000,000 more
documents inserted outside it (invisible to the transaction, at the tail of the _id index). Inside the transaction:
R seeks find({_id: {$gt: 5e6}}).hint({_id: 1}).limit(1) (the bug: nothing visible at or after the seek key) and R
control queries find().hint({_id: 1}).sort({_id: -1}).limit(1) (both arms must walk the run backwards). Per query the
client latency; per loop the server's CPU (/proc), peak RSS and the WiredTiger cursor skip counters.

    run.py measure REPS | report
"""
import json
import os
import shutil
import statistics as st
import subprocess
import sys
import time
import uuid

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
sys.path.insert(0, f"{REPO}/tools/probes")
sys.path.insert(0, f"{REPO}/tools/reproduce")
from mongowire import Int64, Mongo, UUIDBin  # noqa: E402
from pingprobe import reset_hwm  # noqa: E402

ARMS = {"unbounded": "7.0.45", "bounded": "8.2.12"}
DIST = {"7.0.45": "ubuntu2204", "8.2.12": "ubuntu2404"}
PORT = 15475
HEAD, TAIL, R = 1000, int(os.environ.get("TAIL", 1_000_000)), int(os.environ.get("R", 50))
SKIP = ("Total number of entries skipped by cursor next calls", "Total number of entries skipped by cursor prev calls",
        "cursor next calls that skip greater than or equal to 100 entries",
        "cursor prev calls that skip greater than or equal to 100 entries", "cursor search near calls")


def libs():
    """The loader and library path to run the Ubuntu tarballs on NixOS; on Ubuntu they run as they are (None)."""
    if shutil.which("nix-build") is None:
        return None, None
    p = subprocess.run(["nix-build", "--no-out-link", "<nixpkgs>", "-A", "openssl.out", "-A", "curl.out", "-A",
                        "glibc.out"], capture_output=True, text=True, check=True).stdout.split()
    return f"{p[2]}/lib/ld-linux-x86-64.so.2", f"{p[0]}/lib:{p[1]}/lib:{p[2]}/lib"


def cpu_s(pid):
    f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")


def hwm_mb(pid):
    for ln in open(f"/proc/{pid}/status"):
        if ln.startswith("VmHWM:"):
            return int(ln.split()[1]) / 1024


def counters(c):
    cur = c.cmd({"serverStatus": 1})["wiredTiger"]["cursor"]
    return {k: cur.get(k, 0) for k in SKIP}


def loop(c, pid, txn, cmd):
    s0, c0 = counters(c), cpu_s(pid)
    reset_hwm(pid)
    lat = []
    for _ in range(R):
        t0 = time.perf_counter()
        r = c.cmd({**cmd, **txn}, db="t")
        lat.append((time.perf_counter() - t0) * 1e3)
    s1, c1 = counters(c), cpu_s(pid)
    return {"lat_ms": lat, "mean_ms": st.mean(lat), "p50_ms": sorted(lat)[len(lat) // 2], "max_ms": max(lat),
            "server_cpu_ms_per_query": (c1 - c0) * 1e3 / R, "server_peak_rss_mb": hwm_mb(pid),
            "returned": r["cursor"]["firstBatch"][0]["_id"] if r["cursor"]["firstBatch"] else None,
            **{f"d_{k}": (s1[k] - s0[k]) / R for k in SKIP}}


def one(arm, rep, loader, lp):
    v = ARMS[arm]
    tag = f"{arm}-r{rep}"
    rd = f"{D}/runs/{tag}-{int(time.time())}"
    os.makedirs(f"{rd}/db")
    mongod = f"{ROOT}/opt/mongodb-linux-x86_64-{DIST[v]}-{v}/bin/mongod"
    run = [loader, "--library-path", lp, mongod] if loader else [mongod]
    p = subprocess.Popen(["taskset", "-c", "0-7", *run, "--replSet", "rs0", "--port",
                          str(PORT), "--bind_ip", "127.0.0.1", "--dbpath", f"{rd}/db", "--wiredTigerCacheSizeGB", "2",
                          "--setParameter", "transactionLifetimeLimitSeconds=3600", "--logpath", f"{rd}/mongod.log"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    row = {"arm": arm, "version": v, "rep": rep, "head": HEAD, "tail": TAIL, "r": R}
    try:
        for _ in range(300):
            try:
                c = Mongo(PORT, timeout=600)
                break
            except OSError:
                time.sleep(0.1)
        c.cmd({"replSetInitiate": {"_id": "rs0", "members": [{"_id": 0, "host": f"127.0.0.1:{PORT}"}]}})
        for _ in range(300):
            if c.cmd({"hello": 1}).get("isWritablePrimary"):
                break
            time.sleep(0.1)
        c.cmd({"insert": "q", "documents": [{"_id": j + 1, "p": 0} for j in range(HEAD)]}, db="t")
        lsid = {"id": UUIDBin(uuid.uuid4().bytes)}
        txn = {"lsid": lsid, "txnNumber": Int64(1), "autocommit": False}
        c.cmd({"find": "q", "filter": {"_id": 1}, "singleBatch": True, "readConcern": {"level": "snapshot"},
               "startTransaction": True, **txn}, db="t")
        t0 = time.time()
        for b in range(0, TAIL, 10000):
            c.cmd({"insert": "q", "ordered": False,
                   "documents": [{"_id": HEAD + b + j + 1, "p": 0} for j in range(min(10000, TAIL - b))]}, db="t")
        row["tail_insert_s"] = round(time.time() - t0, 2)
        bug = {"find": "q", "filter": {"_id": {"$gt": 5e6}}, "hint": {"_id": 1}, "limit": 1, "singleBatch": True}
        ctl = {"find": "q", "filter": {}, "hint": {"_id": 1}, "sort": {"_id": -1}, "limit": 1, "singleBatch": True}
        for name, cmd in (("seek", bug), ("control", ctl)):
            res = loop(c, p.pid, txn, cmd)
            json.dump(res.pop("lat_ms"), open(f"{D}/data/{tag}-{name}-lat.json", "w"))
            row.update({f"{name}_{k}": v for k, v in res.items()})
        c.cmd({"abortTransaction": 1, **txn})
        row["visible_after_abort"] = c.cmd({"count": "q"}, db="t")["n"]
        try:
            c.cmd({"shutdown": 1, "force": True})
        except (OSError, ConnectionError, Exception):
            pass
    finally:
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    return row


def measure(reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    loader, lp = libs()
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["unbounded", "bounded"] if rep % 2 else ["bounded", "unbounded"]):
                row = one(arm, rep, loader, lp)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: v for k, v in row.items() if not k.startswith("control_d_")}), flush=True)


def table(rows, keys):
    out = ["| metric | 7.0.45 (unbounded) | 8.2.12 (bounded) | 7.0.45 / 8.2.12 |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("unbounded", "bounded"):
            v = [float(r[k]) for r in rows if r["arm"] == arm and r.get(k) is not None]
            if not v:
                cells.append("n/a")
                means[arm] = None
                continue
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = (f"{means['unbounded'] / means['bounded']:.2f}" if means["unbounded"] is not None and means["bounded"]
                 else "")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    keys = []
    for n in ("seek", "control"):
        keys += [f"{n}_mean_ms", f"{n}_p50_ms", f"{n}_max_ms", f"{n}_server_cpu_ms_per_query", f"{n}_server_peak_rss_mb"]
        keys += [f"{n}_d_{k}" for k in SKIP]
    out = [f"# SERVER-56274: index seek past invisible entries, MongoDB {ARMS['unbounded']} vs {ARMS['bounded']}", "",
           f"A single-node replica set; {HEAD:,} documents, a snapshot transaction, then {TAIL:,} more documents it "
           f"cannot see at the tail of the _id index. seek: {R} queries find({{_id: {{$gt: 5e6}}}}).hint({{_id: 1}})."
           f"limit(1) in the transaction; control: {R} of find().sort({{_id: -1}}).limit(1). Client latency per "
           "query, the server's CPU per query and peak RSS over the loop, and per query the WiredTiger cursor "
           "counters (d_*: delta per query). mean, sd [min, max] over repetitions.", ""] + table(rows, keys)
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"measure": lambda: measure(int(a[1])), "report": report}[a[0]]()

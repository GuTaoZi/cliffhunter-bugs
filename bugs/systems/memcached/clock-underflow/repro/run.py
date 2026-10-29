#!/usr/bin/env python3
"""memcached/clock-underflow (queue rank 87): every get hit relinks its item under the global lock for a minute.

Bug (items.c:371 at e31a59121031, do_item_update): `if (it->time < current_time - ITEM_UPDATE_INTERVAL)` with
rel_time_t unsigned (memcached.h:207) and ITEM_UPDATE_INTERVAL 60 (items.c:26). current_time starts at 2
(memcached.c:191 process_started = time(0) - 2; :4711 monotonic_start = ts.tv_sec - 2), so for the first ~58 s of
uptime current_time - 60 wraps to about 4.29e9, the test is true for every item, and every get hit takes the global
cache_lock (items.c:374) to unlink and relink the item at the LRU head. Fixed in d7324b0bd108 (2014-04-17, "fix LRU
contention for first minute of uptime"): the clock starts at ITEM_UPDATE_INTERVAL + 2 (memcached.c:191, 4711), and
the uptime stat subtracts it (memcached.c:2565), so no item is relinked within 60 s of its last bump. Parent
e31a59121031. Design: data/agents/prompts/34 (reply in raw/design.md).

One run: a fresh server (taskset to the server CPUs, -t T, -m 1024, hashpower=20 so the table never expands), 1,000,000
keys k%07d with 64-byte values loaded by 4 processes, then a 25 s measured phase of N client processes (each pinned to
its own client CPU, one TCP_NODELAY connection) sending back-to-back multigets of 64 random existing keys; per-request
latency, keys/s, the server's CPU and peak RSS (tools/reproduce/measure.py). The phase must end before uptime 54 s
(asserted). late: the same after the server has been up 65 s, when the underflow is gone (the arms should match).
check: the LRU head after getting 10,000 keys in descending order (parent: the last key got; fix: the last loaded).
Arms alternate per repetition.

    run.py check | measure CELL REPS | late REPS | report         CELL: A (T=4, N=8) or B (T=16, N=16)
"""
import json
import multiprocessing as mp
import os
import random
import socket
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
from mcclient import MC, start  # noqa: E402

ARMS = {"parent": "e31a59121031", "fix": "d7324b0bd108"}
PORT = 15471
NKEYS, VSIZE, MGET, SECS = 1_000_000, 64, 64, 25
CELLS = {"A": {"T": 4, "N": 8, "server": "0-7", "clients": list(range(16, 24))},
         "B": {"T": 16, "N": 16, "server": "0-15", "clients": list(range(16, 24)) + list(range(40, 48))}}


def binary(arm):
    return f"{ROOT}/build/memcached-{ARMS[arm]}/src/memcached"


def server(arm, cell, log):
    c = CELLS[cell]
    p = subprocess.Popen(["taskset", "-c", c["server"], binary(arm), "-p", str(PORT), "-U", "0", "-l", "127.0.0.1",
                          "-t", str(c["T"]), "-m", "1024", "-o", "hashpower=20"], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(200):
        try:
            MC(PORT, timeout=1).s.close()
            return p, time.time()
        except OSError:
            time.sleep(0.02)
    p.kill()
    raise RuntimeError("memcached did not start")


def loader(lo, hi):
    mc = MC(PORT)
    v = b"x" * VSIZE
    for b in range(lo, hi, 1000):
        r = mc.set_many([("k%07d" % i, v) for i in range(b, min(b + 1000, hi))])
        assert all(x == b"STORED" for x in r), r[:3]


def load():
    step = NKEYS // 4
    ps = [mp.Process(target=loader, args=(i * step, NKEYS if i == 3 else (i + 1) * step)) for i in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
        assert p.exitcode == 0


def client(cpu, seed, secs, q):
    os.sched_setaffinity(0, {cpu})
    rnd = random.Random(seed)
    reqs = [b"get " + b" ".join(b"k%07d" % rnd.randrange(NKEYS) for _ in range(MGET)) + b"\r\n" for _ in range(2048)]
    s = socket.create_connection(("127.0.0.1", PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    lat, n, bad = [], 0, 0
    end = time.perf_counter() + secs
    while True:
        t0 = time.perf_counter()
        if t0 >= end:
            break
        s.sendall(reqs[n % 2048])
        buf = s.recv(1 << 16)
        while not buf.endswith(b"END\r\n"):
            buf += s.recv(1 << 16)
        lat.append(time.perf_counter() - t0)
        if n % 1000 == 0 and buf.count(b"VALUE ") != MGET:
            bad += 1
        n += 1
    q.put({"n": n, "bad": bad, "lat": lat})


def phase(cell, secs):
    c = CELLS[cell]
    q = mp.Queue()
    ps = [mp.Process(target=client, args=(c["clients"][i], 1000 + i, secs, q)) for i in range(c["N"])]
    m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--port", str(PORT), "--seconds",
                          str(secs)], stdout=subprocess.PIPE, text=True)
    for p in ps:
        p.start()
    res = [q.get() for _ in ps]
    for p in ps:
        p.join()
    meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
    lat = sorted(x for r in res for x in r["lat"])
    n = sum(r["n"] for r in res)
    pc = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))] * 1e6
    return {"requests": n, "keys_per_s": n * MGET / secs, "bad": sum(r["bad"] for r in res),
            "p50_us": pc(0.50), "p99_us": pc(0.99), "p999_us": pc(0.999), "max_us": lat[-1] * 1e6,
            "mean_us": st.mean(lat) * 1e6, "server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb")}


def one(arm, cell, rep, late):
    tag = f"{'late-' if late else ''}{cell}-{arm}-r{rep}"
    with open(f"{D}/data/{tag}.log", "w") as log:
        p, t_start = server(arm, cell, log)
        try:
            if late:
                time.sleep(65)
            t0 = time.time()
            load()
            st0 = MC(PORT).stats()
            row = {"arm": arm, "sha": ARMS[arm], "cell": cell, "rep": rep, "late": late,
                   "load_s": round(time.time() - t0, 2), "uptime_start": int(st0["uptime"]),
                   "curr_items": int(st0["curr_items"]), "evictions": int(st0["evictions"])}
            row.update(phase(cell, SECS))
            st1 = MC(PORT).stats()
            row.update({"uptime_end": int(st1["uptime"]), "hash_is_expanding": st1.get("hash_is_expanding"),
                        "evictions_end": int(st1["evictions"]), "since_start_s": round(time.time() - t_start, 1)})
            if not late and row["uptime_end"] > 54:
                row["window_missed"] = True
        finally:
            p.terminate()
            p.wait()
    return row


def check():
    out = []
    for arm in ARMS:
        with open(f"{D}/data/check-{arm}.log", "w") as log:
            p, _ = server(arm, "A", log)
            try:
                mc = MC(PORT)
                v = b"x" * VSIZE
                mc.set_many([("k%07d" % i, v) for i in range(10000)])
                time.sleep(5)
                for b in range(9999, -1, -100):
                    for i in range(b, b - 100, -1):
                        mc.get("k%07d" % i)
                items = mc.stats("items")
                cls = next(k.split(":")[1] for k in items if k.endswith(":number"))
                mc.s.sendall(b"stats cachedump %s 1\r\n" % cls.encode())
                head = mc._readline().decode()
                mc._readline()
                out.append({"arm": arm, "lru_head": head, "age": items.get(f"items:{cls}:age"),
                            "uptime": mc.stats()["uptime"]})
            finally:
                p.terminate()
                p.wait()
    json.dump(out, open(f"{D}/data/check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def measure(cell, reps, late=False):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, cell, rep, late)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps(row), flush=True)


def table(rows, keys):
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
    keys = ["keys_per_s", "p50_us", "p99_us", "p999_us", "max_us", "mean_us", "server_cpu_s", "server_peak_rss_mb",
            "uptime_start", "uptime_end"]
    out = [f"# memcached clock-underflow: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"A fresh server, {NKEYS:,} keys of {VSIZE} bytes, then {SECS} s of closed-loop multigets of {MGET} random "
           "keys per request from pinned client processes (p*_us: per-request latency); the phase ends before uptime "
           "54 s. late: the same after 65 s of uptime. Server CPU and peak RSS over the phase. mean, sd [min, max].", ""]
    for cell in ("A", "B"):
        for late in (False, True):
            rs = [r for r in rows if r["cell"] == cell and r["late"] == late]
            if rs:
                c = CELLS[cell]
                out += [f"## Cell {cell}{' late' if late else ''}: -t {c['T']}, {c['N']} clients", ""] + table(rs, keys) + [""]
    if os.path.exists(f"{D}/data/check.json"):
        out += ["## Decision check: the LRU head after getting 10,000 keys in descending order", "", "```",
                open(f"{D}/data/check.json").read().strip(), "```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "check":
        check()
    elif a[0] == "measure":
        measure(a[1], int(a[2]))
    elif a[0] == "late":
        measure("A", int(a[1]), late=True)
    else:
        report()

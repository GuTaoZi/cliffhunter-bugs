#!/usr/bin/env python3
"""memcached/counter-never-decremented (queue rank 88): the LRU crawler's sleep counter is never counted down.

Bug (items.c at 117dc8dd1f78, item_crawler_thread): the crawler is meant to sleep settings.lru_crawler_sleep us after
every settings.crawls_persleep items; it keeps a local counter crawls_persleep (1341) and tests
`if (crawls_persleep <= 0 && settings.lru_crawler_sleep)` (1403), but nothing decrements it, so the crawler never
sleeps and walks the LRU flat out, holding each class's LRU lock per item. Fixed in 917110af97fa (2016-07-30, "crawler
now uses rate limiter sleeps :("): `crawls_persleep-- <= 0` (1403). Parent 117dc8dd1f78. Design:
data/agents/prompts/34 (reply in raw/design.md); the design rated latency doubtful, because at the default sleep the
fix lowers the crawler's duty only from about 100% to about 45% of a core.

check: 200,000 items, lru_crawler sleep 5000, one crawl of everything, timed (the parent ignores the sleep).
measure SLEEP: a server confined to 2 CPUs (-t 2), 1,000,000 keys of 100 bytes, lru_crawler_sleep SLEEP us; phase 0
(10 s) closed-loop 16-key multigets from 8 pinned clients, no crawl; phase 1 (30 s) the same with a crawl of everything
requested every 2 ms. Per phase: request latency, keys/s, the server's CPU and peak RSS (tools/reproduce/measure.py),
crawler_items_checked. The bug shows if phase 1 costs the parent more than the fix while phase 0 is equal.

    run.py check | measure SLEEP REPS | report
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
from mcclient import MC  # noqa: E402

ARMS = {"parent": "117dc8dd1f78", "fix": "917110af97fa"}
PORT = 15479
NKEYS, VSIZE, MGET, CLIENTS = 1_000_000, 100, 16, list(range(16, 24))


def server(arm, cpus, threads, opts, log):
    p = subprocess.Popen(["taskset", "-c", cpus, f"{ROOT}/build/memcached-{ARMS[arm]}/src/memcached", "-p", str(PORT),
                          "-U", "0", "-l", "127.0.0.1", "-t", str(threads), "-m", "1024", "-o", opts],
                         stdout=log, stderr=subprocess.STDOUT)
    for _ in range(200):
        try:
            MC(PORT, timeout=1).s.close()
            return p
        except OSError:
            time.sleep(0.02)
    p.kill()
    raise RuntimeError("memcached did not start")


def loader(lo, hi):
    mc = MC(PORT)
    v = b"x" * VSIZE
    for b in range(lo, hi, 1000):
        assert all(x == b"STORED" for x in mc.set_many([("k%07d" % i, v) for i in range(b, min(b + 1000, hi))]))


def load(n):
    step = n // 4
    ps = [mp.Process(target=loader, args=(i * step, n if i == 3 else (i + 1) * step)) for i in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()


def client(cpu, seed, secs, q):
    os.sched_setaffinity(0, {cpu})
    rnd = random.Random(seed)
    reqs = [b"get " + b" ".join(b"k%07d" % rnd.randrange(NKEYS) for _ in range(MGET)) + b"\r\n" for _ in range(2048)]
    s = socket.create_connection(("127.0.0.1", PORT))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    lat, n = [], 0
    end = time.perf_counter() + secs
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        s.sendall(reqs[n % 2048])
        buf = s.recv(1 << 16)
        while not buf.endswith(b"END\r\n"):
            buf += s.recv(1 << 16)
        lat.append(time.perf_counter() - t0)
        n += 1
    q.put(lat)


def crawler(secs, q):
    mc = MC(PORT)
    ok = busy = 0
    end = time.time() + secs
    while time.time() < end:
        r = mc.raw("lru_crawler crawl all")
        ok += r == b"OK"
        busy += r.startswith(b"BUSY")
        time.sleep(0.002)
    q.put({"crawl_ok": ok, "crawl_busy": busy})


def phase(pid, secs, crawl):
    q, cq = mp.Queue(), mp.Queue()
    st0 = MC(PORT).stats()
    m = subprocess.Popen([sys.executable, f"{REPO}/tools/reproduce/measure.py", "--pid", str(pid), "--seconds",
                          str(secs)], stdout=subprocess.PIPE, text=True)
    ps = [mp.Process(target=client, args=(c, 100 + c, secs, q)) for c in CLIENTS]
    cr = mp.Process(target=crawler, args=(secs, cq)) if crawl else None
    for p in ps + ([cr] if cr else []):
        p.start()
    lat = sorted(x for _ in ps for x in q.get())
    for p in ps:
        p.join()
    out = cq.get() if cr else {}
    if cr:
        cr.join()
    meas = json.loads(m.communicate()[0].strip().splitlines()[-1])
    st1 = MC(PORT).stats()
    pc = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))] * 1e6
    out.update({"keys_per_s": len(lat) * MGET / secs, "p50_us": pc(0.5), "p99_us": pc(0.99), "p999_us": pc(0.999),
                "mean_us": st.mean(lat) * 1e6, "server_cpu_s": meas.get("cpu_s"), "server_peak_rss_mb": meas.get("peak_rss_mb"),
                "items_checked_per_s": (int(st1.get("crawler_items_checked", 0)) - int(st0.get("crawler_items_checked", 0))) / secs})
    return out


def one(arm, sleep_us, rep):
    tag = f"s{sleep_us}-{arm}-r{rep}"
    opts = f"lru_crawler,lru_crawler_sleep={sleep_us},hashpower=21"
    with open(f"{D}/data/{tag}.log", "w") as log:
        p = server(arm, "0-1", 2, opts, log)
        try:
            load(NKEYS)
            s = MC(PORT).stats()
            row = {"arm": arm, "sha": ARMS[arm], "sleep_us": sleep_us, "rep": rep, "curr_items": int(s["curr_items"]),
                   "evictions": int(s["evictions"])}
            row.update({f"p0_{k}": v for k, v in phase(p.pid, 10, False).items()})
            row.update({f"p1_{k}": v for k, v in phase(p.pid, 30, True).items()})
        finally:
            p.terminate()
            p.wait()
    return row


def check():
    os.makedirs(f"{D}/data", exist_ok=True)
    out = []
    for arm in ARMS:
        with open(f"{D}/data/check-{arm}.log", "w") as log:
            p = server(arm, "0-7", 4, "lru_crawler,hashpower=20", log)
            try:
                load(200_000)
                mc = MC(PORT)
                assert mc.raw("lru_crawler sleep 5000") == b"OK"
                t0 = time.time()
                r = mc.raw("lru_crawler crawl all")
                while mc.stats().get("lru_crawler_running", "0") != "0":
                    time.sleep(0.005)
                out.append({"arm": arm, "crawl_reply": r.decode(), "crawl_s": round(time.time() - t0, 3),
                            "items_checked": int(mc.stats().get("crawler_items_checked", 0))})
            finally:
                p.terminate()
                p.wait()
    json.dump(out, open(f"{D}/data/check.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


def measure(sleep_us, reps):
    os.makedirs(f"{D}/data", exist_ok=True)
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, sleep_us, rep)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row[k] for k in ("arm", "sleep_us", "rep", "p0_keys_per_s", "p1_keys_per_s",
                                                      "p0_p99_us", "p1_p99_us", "p1_items_checked_per_s",
                                                      "p1_server_cpu_s")}), flush=True)


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
    keys = [f"{p}_{k}" for p in ("p0", "p1") for k in ("keys_per_s", "p50_us", "p99_us", "p999_us", "server_cpu_s",
                                                        "server_peak_rss_mb", "items_checked_per_s")]
    out = [f"# memcached counter-never-decremented: parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"A server confined to 2 CPUs (-t 2), {NKEYS:,} keys of {VSIZE} bytes; p0: 10 s of closed-loop {MGET}-key "
           "multigets from 8 pinned clients, no crawl; p1: 30 s of the same with a crawl of everything requested every "
           "2 ms. mean, sd [min, max].", ""]
    for s in sorted({r["sleep_us"] for r in rows}):
        out += [f"## lru_crawler_sleep {s} us", ""] + table([r for r in rows if r["sleep_us"] == s], keys) + [""]
    if os.path.exists(f"{D}/data/check.json"):
        out += ["## Check: one crawl of 200,000 items with lru_crawler sleep 5000", "", "```",
                open(f"{D}/data/check.json").read().strip(), "```"]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    a = sys.argv[1:]
    {"check": check, "measure": lambda: measure(int(a[1]), int(a[2])), "report": report}[a[0]]()

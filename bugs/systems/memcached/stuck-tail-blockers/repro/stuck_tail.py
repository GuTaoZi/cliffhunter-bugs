#!/usr/bin/env python3
"""One run of the stuck-tail workload against one memcached binary.

    stuck_tail.py --bin MEMCACHED --arm NAME --config {refhang,thousands-aged,thousands-fresh}
                  --rep N --port P --out RUNS.jsonl

Phases (only phase 4 is measured):
  1. start memcached (-m MEM, 4 threads), fill one slab class with NFILL keys so it evicts;
  2. a "hang" client sets a small SO_RCVBUF, sends one multi-get for NHANG of the oldest live keys,
     and never reads its socket: the server holds a reference on every fetched item until the
     reply is fully written, i.e. forever;
  3. (thousands-aged only) sleep AGE_S so those items become older than ITEM_UPDATE_INTERVAL (60 s);
  4. measured: a writer sets NSETS new keys of the same size, one at a time, recording each reply
     (STORED or SERVER_ERROR out of memory) and its latency; the server's CPU and peak RSS over the
     phase come from tools/reproduce/measure.py's Sampler;
  5. counters (stats items for the class: outofmemory, evicted, tailrepairs), the hang socket's
     server-side send queue, a hit check on the new keys, then the hang client disconnects and 50
     more sets show whether writes recover.
"""
import argparse
import importlib.util
import json
import os
import socket
import statistics as st
import subprocess
import sys
import time

TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../tools/reproduce"))
sys.path.insert(0, TOOLS)
from mcclient import MC, start  # noqa: E402

_spec = importlib.util.spec_from_file_location("measure", os.path.join(TOOLS, "measure.py"))
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)

CONFIGS = {
    # t/refhang.t at f2a4e5b491ed: -m 6, 66560-byte values, 120 keys, multi-get of key0..key114;
    # the test then does 119 sets; here 2000 (the first 119 are the test's).
    "refhang": dict(mem=6, vsize=66560, nfill=120, nhang=115, hang_from_live=False, nsets=2000, age_s=0),
    # the commit message's trigger at its scale: a client fetches 3000 keys (the oldest live ones,
    # 6 MB of replies, more than the 4 MB tcp_wmem max) and never reads; the items are older than
    # 60 s when the writes come, as in production where LRU turnover is slower than a minute.
    "thousands-aged": dict(mem=64, vsize=2048, nfill=40000, nhang=3000, hang_from_live=True, nsets=20000, age_s=63),
    # boundary: the same, but the items are fresh (< 60 s), so the fix's relink does not fire and
    # its 1000-item walk is the only relief.
    "thousands-fresh": dict(mem=64, vsize=2048, nfill=40000, nhang=3000, hang_from_live=True, nsets=20000, age_s=0),
}


def key(i):
    return "key%d" % i


def server_sendq(port, client_port):
    """tx_queue of the server-side socket of the connection to client_port (bytes it cannot send)."""
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for ln in open(table).read().splitlines()[1:]:
                f = ln.split()
                lp = int(f[1].rsplit(":", 1)[1], 16)
                rp = int(f[2].rsplit(":", 1)[1], 16)
                if lp == port and rp == client_port:
                    tx, rx = f[4].split(":")
                    return int(tx, 16)
        except OSError:
            pass
    return None


def cls_stats(mc):
    it = mc.stats("items")
    cls = {}
    for k, v in it.items():
        _, c, name = k.split(":")
        cls.setdefault(int(c), {})[name] = int(v)
    return cls


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--config", required=True, choices=CONFIGS)
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--port", type=int, default=15440)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nsets", type=int)
    a = ap.parse_args()
    cfg = dict(CONFIGS[a.config])
    if a.nsets:
        cfg["nsets"] = a.nsets
    assert 15440 <= a.port <= 15449
    logdir = os.path.join(os.path.dirname(os.path.abspath(a.out)), "logs")
    os.makedirs(logdir, exist_ok=True)
    log = open(os.path.join(logdir, f"mc-{a.config}-{a.arm}-{a.rep}.log"), "w")
    proc = start(a.bin, a.port, ["-m", str(cfg["mem"]), "-t", "4"], log)
    rec = {"arm": a.arm, "config": a.config, "rep": a.rep, "bin": a.bin, **cfg,
           "date": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        mc = MC(a.port, timeout=30)
        val = b"B" * cfg["vsize"]
        # 1. fill
        if cfg["nfill"] <= 1000:
            for i in range(cfg["nfill"]):
                assert mc.set(key(i), val) == b"STORED", key(i)
        else:
            for b0 in range(0, cfg["nfill"], 500):
                rs = mc.set_many([(key(i), val) for i in range(b0, min(cfg["nfill"], b0 + 500))])
                assert all(r == b"STORED" for r in rs), set(rs)
        s0 = mc.stats()
        cs = cls_stats(mc)
        cid = max(cs, key=lambda c: cs[c]["number"])
        rec["slab_class"] = cid
        rec["fill_curr_items"] = int(s0["curr_items"])
        rec["fill_evictions"] = int(s0["evictions"])
        assert rec["fill_evictions"] > 0, "fill did not evict: the class is not full"
        # 2. hang client
        first = cfg["nfill"] - rec["fill_curr_items"] if cfg["hang_from_live"] else 0
        hang_keys = [key(i) for i in range(first, first + cfg["nhang"])]
        hs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        hs.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        hs.connect(("127.0.0.1", a.port))
        hs.sendall(("get " + " ".join(hang_keys) + "\r\n").encode())
        time.sleep(0.5)
        s1 = mc.stats()
        rec["hang_get_hits"] = int(s1["get_hits"]) - int(s0["get_hits"])
        rec["hang_sendq_bytes"] = server_sendq(a.port, hs.getsockname()[1])
        # 3. age
        if cfg["age_s"]:
            time.sleep(cfg["age_s"])
        c0 = cls_stats(mc)[cid]
        # 4. measured write phase
        sampler = measure.Sampler(proc.pid)
        try:
            open(f"/proc/{proc.pid}/clear_refs", "w").write("5")
        except OSError:
            pass
        sampler.poll()
        sampler.start()
        lat, ok, oom, other = [], 0, 0, 0
        first_ok, oom119 = None, 0
        t0 = time.perf_counter()
        base = cfg["nfill"] + 1
        for j in range(cfg["nsets"]):
            t = time.perf_counter()
            r = mc.set(key(base + j), val)
            lat.append(time.perf_counter() - t)
            if r == b"STORED":
                ok += 1
                if first_ok is None:
                    first_ok = j
            elif r.startswith(b"SERVER_ERROR out of memory"):
                oom += 1
                if j < 119:
                    oom119 += 1
            else:
                other += 1
        wall = time.perf_counter() - t0
        sampler.stop.set()
        sampler.join(timeout=2)
        sampler.poll()
        c1 = cls_stats(mc)[cid]
        rec.update({
            "sets_ok": ok, "sets_oom": oom, "sets_other": other,
            "oom_frac": oom / cfg["nsets"], "first_ok_index": first_ok,
            "oom_in_first_119": oom119,
            "lat_mean_us": st.mean(lat) * 1e6, "lat_p50_us": pct(lat, 50) * 1e6,
            "lat_p99_us": pct(lat, 99) * 1e6, "lat_max_us": max(lat) * 1e6,
            "write_wall_s": wall, "sets_per_s": cfg["nsets"] / wall,
            "server_cpu_s": sampler.cpu_s(), "server_peak_rss_mb": round(sampler.peak / 1024, 1),
            "outofmemory_delta": c1["outofmemory"] - c0["outofmemory"],
            "evicted_delta": c1["evicted"] - c0["evicted"],
            "tailrepairs_delta": c1["tailrepairs"] - c0["tailrepairs"],
            "hang_sendq_after_bytes": server_sendq(a.port, hs.getsockname()[1]),
        })
        # 5. hit check on new keys (last 100 set), then release the hang client and test recovery
        hits = 0
        for j in range(max(0, cfg["nsets"] - 100), cfg["nsets"]):
            hits += mc.get(key(base + j)) is not None
        rec["new_key_hits_last100"] = hits
        hs.close()
        time.sleep(0.5)
        rok = 0
        for j in range(50):
            rok += mc.set(key(base + cfg["nsets"] + j), val) == b"STORED"
        rec["recovery_ok_of_50"] = rok
        rec["server_rss_end_mb"] = round(measure.hwm_kb(proc.pid) / 1024, 1)
        mc.s.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    with open(a.out, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    main()

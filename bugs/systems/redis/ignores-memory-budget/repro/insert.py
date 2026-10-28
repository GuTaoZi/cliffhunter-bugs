#!/usr/bin/env python3
"""Measured phase: insert COUNT new keys (SET new:i value:i) pipelined in batches, then wait for the
server to settle (used_memory back under maxmemory and the keyspace dict no longer rehashing, or a
timeout). Records per-batch latency, OOM rejections, and a 50 ms trace of used_memory, evicted_keys
and the key count taken over a second connection. Writes one JSON file.

    insert.py --port P --count K --batch B --settle S --out FILE
"""
import os
import argparse
import json
import sys
import threading
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../tools/reproduce")))
from respclient import Resp  # noqa: E402


def snapshot(r):
    """O(1) server state: used_memory, evicted_keys, key count and bucket count of db0's main dict.
    Bucket count (ht[0].size + ht[1].size) is derived from MEMORY STATS' overhead.hashtable.main =
    keys*sizeof(dictEntry)=24 + slots*8 + keys*sizeof(robj)=16 (object.c getMemoryOverheadData)."""
    mem, st, ms = r.send([["INFO", "memory"], ["INFO", "stats"], ["MEMORY", "STATS"]])
    d = {}
    for blob in (mem, st):
        for ln in blob.decode().splitlines():
            if ":" in ln and not ln.startswith("#"):
                k, v = ln.split(":", 1)
                d[k] = v.strip()
    m = dict(zip(ms[0::2], ms[1::2]))
    keys = m.get(b"keys.count", 0)
    db0 = dict(zip(m[b"db.0"][0::2], m[b"db.0"][1::2])) if b"db.0" in m else {}
    ohm = db0.get(b"overhead.hashtable.main", 0)
    slots = (ohm - keys * 40) // 8 if ohm else 0
    return {"t": time.time(), "used_memory": int(d["used_memory"]),
            "evicted_keys": int(d["evicted_keys"]), "keys": keys, "slots": slots,
            "rehashing": slots & (slots - 1) != 0}


class Tracer(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.r, self.stop, self.rows = Resp(port), threading.Event(), []

    def run(self):
        while not self.stop.is_set():
            self.rows.append(snapshot(self.r))
            self.stop.wait(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--settle", type=float, default=15.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    r = Resp(a.port)
    maxmem = int(r.info("memory")["maxmemory"])
    tr = Tracer(a.port)
    tr.start()
    lat, oom, other_err = [], 0, 0
    t0 = time.time()
    for b in range(0, a.count, a.batch):
        cmds = [["SET", f"new:{i}", f"value:{i}"] for i in range(b, min(b + a.batch, a.count))]
        s = time.perf_counter()
        rep = r.send(cmds)
        lat.append(time.perf_counter() - s)
        for x in rep:
            if isinstance(x, RuntimeError):
                if str(x).startswith("OOM"):
                    oom += 1
                else:
                    other_err += 1
    t_ins = time.time() - t0
    # Settle: let incremental eviction / rehash finish (or time out), still inside the measured window.
    t1 = time.time()
    while time.time() - t1 < a.settle:
        s = tr.rows[-1] if tr.rows else None
        if s and s["used_memory"] <= maxmem and not s["rehashing"] and time.time() - t1 > 0.5:
            break
        time.sleep(0.1)
    tr.stop.set()
    tr.join(timeout=2)
    final = snapshot(r)
    lat_sorted = sorted(lat)
    q = lambda p: lat_sorted[min(len(lat_sorted) - 1, int(p * len(lat_sorted)))]
    out = {"count": a.count, "batch": a.batch, "insert_wall_s": t_ins, "settle_s": time.time() - t1,
           "batches": len(lat), "lat_mean_ms": 1e3 * sum(lat) / len(lat), "lat_p50_ms": 1e3 * q(0.5),
           "lat_p99_ms": 1e3 * q(0.99), "lat_p999_ms": 1e3 * q(0.999), "lat_max_ms": 1e3 * lat_sorted[-1],
           "oom_rejected": oom, "other_errors": other_err, "maxmemory": maxmem, "final": final,
           "trace_peak_used_memory": max(x["used_memory"] for x in tr.rows + [final]),
           "trace_max_over_maxmemory": max(x["used_memory"] for x in tr.rows + [final]) - maxmem,
           "trace": tr.rows, "lat_series_ms": [round(1e3 * x, 3) for x in lat]}
    json.dump(out, open(a.out, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

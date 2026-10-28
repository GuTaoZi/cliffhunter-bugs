#!/usr/bin/env python3
"""One repetition of one arm.

  1. start redis-server (arm's binary) on PORT with maxmemory 0 and the given policy;
  2. DEBUG POPULATE N (N a power of two: db0's dict is pre-sized to exactly N buckets, load factor 1.0);
  3. wait 1 s, read used_memory, CONFIG SET maxmemory used_memory + MARGIN, CONFIG RESETSTAT;
  4. measured phase (tools/reproduce/measure.py on the server pid): insert.py inserts K new keys
     and waits for the server to settle;
  5. record final state (DBSIZE, evicted_keys, DEBUG HTSTATS 0 table size), stop the server.

    run.py --arm NAME --bin PATH --port P --n N --margin BYTES --k K --policy POLICY --rep R --outdir DIR
"""
import argparse
import json
import os
import subprocess
import sys
import time

TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../../tools/reproduce"))
sys.path.insert(0, TOOLS)
from respclient import Resp, start, stop  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def table_sizes(r):
    ht = r.cmd("DEBUG", "HTSTATS", "0")
    ht = ht.decode() if isinstance(ht, bytes) else str(ht)
    main = ht.split("[Expires")[0]
    return [int(x.split(":")[1]) for x in main.splitlines() if x.strip().startswith("table size:")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--margin", type=int, required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--settle", type=float, default=15.0)
    ap.add_argument("--policy", default="allkeys-lru")
    ap.add_argument("--rep", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    assert 15430 <= a.port <= 15439
    os.makedirs(a.outdir, exist_ok=True)
    tag = f"{a.arm}-{a.policy}-n{a.n}-r{a.rep}"
    log = open(os.path.join(a.outdir, tag + ".server.log"), "w")
    p = start(a.bin, a.port, ["--maxmemory", "0", "--maxmemory-policy", a.policy,
                              "--dir", a.outdir, "--dbfilename", tag + ".rdb"], log)
    try:
        r = Resp(a.port, timeout=600)
        assert r.cmd("DEBUG", "POPULATE", str(a.n)) == b"OK"
        time.sleep(1.0)
        before_sizes = table_sizes(r)
        used = int(r.info("memory")["used_memory"])
        maxmem = used + a.margin
        assert r.cmd("CONFIG", "SET", "maxmemory", str(maxmem)) == b"OK"
        assert r.cmd("CONFIG", "RESETSTAT") == b"OK"
        lat_file = os.path.join(a.outdir, tag + ".insert.json")
        m = subprocess.run([sys.executable, os.path.join(TOOLS, "measure.py"), "--pid", str(p.pid), "--",
                            sys.executable, os.path.join(HERE, "insert.py"), "--port", str(a.port),
                            "--count", str(a.k), "--batch", str(a.batch), "--settle", str(a.settle),
                            "--out", lat_file], capture_output=True, text=True)
        meas = json.loads(m.stdout.strip().splitlines()[-1])
        ins = json.load(open(lat_file))
        info = r.info("all")
        after_sizes = table_sizes(r)
        res = {"arm": a.arm, "policy": a.policy, "n": a.n, "margin": a.margin, "k": a.k, "rep": a.rep,
               "binary": a.bin, "used_before": used, "maxmemory": maxmem,
               "table_sizes_before": before_sizes, "table_sizes_after": after_sizes,
               "dbsize_after": r.cmd("DBSIZE"), "evicted_keys": int(info["evicted_keys"]),
               "used_memory_after": int(info["used_memory"]),
               "used_memory_peak_since_start": int(info["used_memory_peak"]),
               "server": meas,
               **{k: v for k, v in ins.items() if k not in ("trace", "lat_series_ms", "final")},
               "final_snapshot": ins["final"]}
        json.dump(res, open(os.path.join(a.outdir, tag + ".result.json"), "w"), indent=1)
        print(json.dumps({k: res[k] for k in ("arm", "policy", "n", "rep", "table_sizes_before",
                                               "table_sizes_after", "dbsize_after", "evicted_keys",
                                               "oom_rejected", "trace_max_over_maxmemory",
                                               "insert_wall_s", "lat_p50_ms", "lat_p99_ms", "lat_max_ms")}
                         | {"server_cpu_s": meas["cpu_s"], "server_peak_rss_mb": meas["peak_rss_mb"],
                            "wall_s": meas["wall_s"]}))
    finally:
        stop(p)
        log.close()
        try:
            os.remove(os.path.join(a.outdir, tag + ".rdb"))
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""valkey/memory-guard-blocks-shrink: buggy parent vs fix, what is left after maxmemory is lowered.

Bug (src/hashtable.c resize(), src/server.c resizeAllowed): the guard that refuses a new table
allocation when it would cross maxmemory also refused SHRINKS, which allocate briefly but save
memory. Under eviction the main key table stays huge and gets sparser; when maxmemory is lowered
a lot, the bucket array alone can exceed the limit, so eviction removes every key and writes still
fail. Fixed by 130ea3973ba9 (2025-07-04), which lets shrinks cross maxmemory.

Each run (the commit's own recipe): fresh server, maxmemory 2gb, allkeys-lru, DEBUG POPULATE
20,000,000; then CONFIG SET maxmemory 200mb and poll every second for SETTLE_S seconds: DBSIZE,
used_memory, the main table's bucket count (DEBUG HTSTATS). Then try SET foo bar. Server CPU and
peak RSS over the settle window from tools/reproduce/measure.py. Arms alternate; buggy repeated last.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "reproduce"))
from respclient import Resp, start, stop  # noqa: E402

ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))


def build_path(rev):
    sha = subprocess.run(["git", "-C", f"{ROOT}/src/valkey", "rev-parse", rev], capture_output=True,
                         text=True, check=True).stdout.strip()
    return f"{ROOT}/build/valkey-{sha[:12]}/src/src/valkey-server"


ARMS = {"buggy": build_path("130ea3973ba9~1"), "fixed": build_path("130ea3973ba9")}
PORT = 15422


def table_size(r):
    txt = r.cmd("DEBUG", "HTSTATS", "0")
    txt = txt.decode() if isinstance(txt, bytes) else str(txt)
    m = re.search(r"table size: (\d+)", txt)
    return int(m.group(1)) if m else None


def one(arm, settle_s, log):
    p = start(ARMS[arm], PORT, ["--maxmemory", "2gb", "--maxmemory-policy", "allkeys-lru",
                                "--enable-debug-command", "yes"], log)
    try:
        r = Resp(PORT, timeout=300)
        assert r.cmd("DEBUG", "POPULATE", "20000000") == b"OK"
        before = {"dbsize": r.cmd("DBSIZE"), "table": table_size(r),
                  "used_mb": int(r.info("memory")["used_memory"]) / 2**20}
        res = {}
        th = threading.Thread(target=lambda: res.update(json.loads(subprocess.run(
            [sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(p.pid), "--seconds",
             str(settle_s)], capture_output=True, text=True).stdout)))
        th.start()
        r.cmd("CONFIG", "SET", "maxmemory", "200mb")
        series = []
        for _ in range(int(settle_s)):
            time.sleep(1)
            series.append({"dbsize": r.cmd("DBSIZE"), "used_mb": int(r.info("memory")["used_memory"]) / 2**20,
                           "table": table_size(r)})
        th.join()
        set_reply = r.cmd("SET", "foo", "bar")
        return {"arm": arm, "before": before, "series": series, "final_dbsize": series[-1]["dbsize"],
                "final_used_mb": series[-1]["used_mb"], "final_table": series[-1]["table"],
                "set_ok": set_reply == b"OK", "set_reply": str(set_reply)[:80],
                "cpu_s": res.get("cpu_s"), "peak_rss_mb": res.get("peak_rss_mb"), "settle_wall_s": res.get("wall_s")}
    finally:
        stop(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--settle", type=float, default=30)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "valkey-memory-guard-blocks-shrink", "raw"), exist_ok=True)
    log = open(os.path.join(REPO, "data", "experiments", "valkey-memory-guard-blocks-shrink", "raw", "server.log"), "w")
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "valkey-memory-guard-blocks-shrink", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, a.settle, log)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"dbsize {rec['before']['dbsize']} -> {rec['final_dbsize']}", f"table {rec['before']['table']} -> {rec['final_table']}",
                  f"used {rec['final_used_mb']:.0f}MB", f"SET ok={rec['set_ok']}", f"cpu {rec['cpu_s']}s", flush=True)


if __name__ == "__main__":
    main()

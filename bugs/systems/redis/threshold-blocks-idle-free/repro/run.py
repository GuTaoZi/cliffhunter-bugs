#!/usr/bin/env python3
"""redis/threshold-blocks-idle-free: buggy parent vs fix, memory held by idle clients.

Bug (src/server.c clientsCronResizeQueryBuffer): a client's query buffer was trimmed only if it
was larger than PROTO_RESIZE_THRESHOLD (32 KB), even when the client had been idle for > 2 s, so
an idle client whose buffer was below 32 KB but still wasting > 4 KB kept it forever. Fixed by
0a9377535b6f (2021-08-06), which drops the size threshold on the idle path.

Each run: fresh server; N clients connect, each sends PING and reads +PONG, then all stay idle.
After IDLE_S seconds (the cron visits every client about once per second at hz 10):
used_memory, the summed qbuf + qbuf-free over CLIENT LIST, server RSS; CPU and peak memory over
the idle window from tools/reproduce/measure.py. Arms alternate order per repetition; buggy is repeated
last as a drift control.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "reproduce"))
from respclient import Resp, start, stop  # noqa: E402

ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))


def build_path(rev):
    sha = subprocess.run(["git", "-C", f"{ROOT}/src/redis", "rev-parse", rev], capture_output=True,
                         text=True, check=True).stdout.strip()
    return f"{ROOT}/build/redis-{sha[:12]}/src/src/redis-server"


ARMS = {"buggy": build_path("0a9377535b6f~1"), "fixed": build_path("0a9377535b6f")}
PORT = 15412


def rss_kb(pid):
    return next(int(l.split()[1]) for l in open(f"/proc/{pid}/status") if l.startswith("VmRSS:"))


def one(arm, n, idle_s, log):
    p = start(ARMS[arm], PORT, ["--maxclients", str(n + 100)], log)
    socks = []
    try:
        ctl = Resp(PORT)
        base_used = int(ctl.info("memory")["used_memory"])
        for _ in range(n):
            s = socket.create_connection(("127.0.0.1", PORT))
            s.sendall(b"*1\r\n$4\r\nPING\r\n")
            socks.append(s)
        for s in socks:
            assert s.recv(16).startswith(b"+PONG")
        m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(p.pid),
                            "--seconds", str(idle_s)], capture_output=True, text=True)
        rec = json.loads(m.stdout)
        used = int(ctl.info("memory")["used_memory"])
        cl = ctl.cmd("CLIENT", "LIST").decode().splitlines()
        qb = 0
        for line in cl:
            f = dict(kv.split("=", 1) for kv in line.split() if "=" in kv)
            qb += int(f.get("qbuf", 0)) + int(f.get("qbuf-free", 0))
        rec.update({"arm": arm, "clients": n, "used_memory_mb": used / 2**20,
                    "used_by_clients_mb": (used - base_used) / 2**20, "qbuf_total_mb": qb / 2**20,
                    "qbuf_per_client_kb": qb / 1024 / max(1, len(cl)), "rss_mb": rss_kb(p.pid) / 1024,
                    "cpu_pct": 100 * rec["cpu_s"] / rec["wall_s"]})
        return rec
    finally:
        for s in socks:
            s.close()
        stop(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--clients", type=int, default=5000)
    ap.add_argument("--idle", type=float, default=5)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "redis-threshold-blocks-idle-free", "raw"), exist_ok=True)
    log = open(os.path.join(REPO, "data", "experiments", "redis-threshold-blocks-idle-free", "raw", "server.log"), "w")
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "redis-threshold-blocks-idle-free", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, a.clients, a.idle, log)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"clients-used {rec['used_by_clients_mb']:.1f} MB", f"qbuf {rec['qbuf_total_mb']:.1f} MB",
                  f"rss {rec['rss_mb']:.0f} MB", f"cpu {rec['cpu_pct']:.2f}%", flush=True)


if __name__ == "__main__":
    main()

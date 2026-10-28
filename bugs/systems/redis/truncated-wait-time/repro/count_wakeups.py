#!/usr/bin/env python3
"""redis/truncated-wait-time: count event-loop waits on an idle server, buggy parent vs fix.

The CPU numbers in run.py are a few 10 ms ticks per 30 s, close to /proc's resolution. This shows
the mechanism directly: the server runs under strace, which records every epoll_wait call and its
timeout argument. The buggy loop should make many calls with timeout 0 (the busy wait before each
timer); the fixed loop should make about one call per timer, never with timeout 0. strace slows
each call, so the buggy counts are a lower bound on what an untraced server does.

Writes raw/wakeups.jsonl: arm, hz, seconds, calls, calls_timeout_0, calls per second.
"""
import tempfile
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "reproduce"))
from respclient import Resp  # noqa: E402

BUILD = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs")) + "/build"
ARMS = {"buggy": f"{BUILD}/redis-5e3a15ae1b58/src/src/redis-server",
        "fixed": f"{BUILD}/redis-175a9e3199f7/src/src/redis-server"}
PORT = 15411
TMP = tempfile.mkdtemp(prefix="cliffhunter-")
CALL = re.compile(r"epoll_(?:p)?wait\(\d+, .*?, \d+, (-?\d+)")


def one(arm, hz, seconds):
    trace = os.path.join(TMP, f"redis-wakeups-{arm}-{hz}.strace")
    log = open(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw", "server.log"), "a")
    p = subprocess.Popen(["strace", "-f", "-e", "trace=epoll_wait,epoll_pwait", "-o", trace, ARMS[arm],
                          "--port", str(PORT), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no",
                          "--hz", str(hz)], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(400):
        try:
            if Resp(PORT, timeout=1).cmd("PING") == b"PONG":
                break
        except OSError:
            time.sleep(0.05)
    time.sleep(1)
    start = os.path.getsize(trace)
    time.sleep(seconds)
    with open(trace) as f:
        f.seek(start)
        lines = f.read().splitlines()
    child = subprocess.run(["pgrep", "-P", str(p.pid)], capture_output=True, text=True).stdout.split()
    for c in child:
        os.kill(int(c), signal.SIGTERM)
    p.wait(timeout=30)
    timeouts = [int(m.group(1)) for m in map(CALL.search, lines) if m]
    os.remove(trace)
    return {"arm": arm, "hz": hz, "seconds": seconds, "calls": len(timeouts),
            "calls_timeout_0": sum(1 for t in timeouts if t == 0),
            "calls_per_s": round(len(timeouts) / seconds, 1)}


def main():
    os.makedirs(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw"), exist_ok=True)
    with open(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw", "wakeups.jsonl"), "w") as out:
        for hz in (10, 100):
            for arm in ("buggy", "fixed", "buggy", "fixed"):
                rec = one(arm, hz, 10)
                out.write(json.dumps(rec) + "\n")
                out.flush()
                print(rec, flush=True)


if __name__ == "__main__":
    main()

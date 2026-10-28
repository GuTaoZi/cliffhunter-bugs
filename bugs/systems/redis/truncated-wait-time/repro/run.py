#!/usr/bin/env python3
"""redis/truncated-wait-time: buggy parent vs fix, idle server CPU.

Bug (src/ae.c): the next timer is computed in microseconds but the event-loop sleep in whole
milliseconds, truncated, so the loop wakes up to 1 ms early, finds no timer due, and sleeps
0 ms again and again until the right microsecond: a busy loop in the last millisecond before
every timer. Fixed by 175a9e3199f7 (2021-04-13), which works in microseconds and rounds up.

Each run: fresh server, no clients except one INFO at the end, IDLE_S seconds measured with
tools/reproduce/measure.py. Done at hz 10 (default) and hz 100. Arms alternate order per repetition; the
first arm is repeated at the end of each hz block as a drift control.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, os.path.join(REPO, "tools", "reproduce"))
from respclient import Resp, start, stop  # noqa: E402

BUILD = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs")) + "/build"
ARMS = {"buggy": f"{BUILD}/redis-5e3a15ae1b58/src/src/redis-server",
        "fixed": f"{BUILD}/redis-175a9e3199f7/src/src/redis-server"}
PORT = 15411


def one(arm, hz, idle_s, log):
    p = start(ARMS[arm], PORT, ["--hz", str(hz)], log)
    try:
        time.sleep(1)
        m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(p.pid),
                            "--seconds", str(idle_s)], capture_output=True, text=True)
        rec = json.loads(m.stdout)
        inf = Resp(PORT).info("server")
        rec.update({"arm": arm, "hz": hz, "cpu_pct": 100 * rec["cpu_s"] / rec["wall_s"],
                    "version": inf.get("redis_version")})
        return rec
    finally:
        stop(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--idle", type=float, default=30)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw"), exist_ok=True)
    log = open(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw", "server.log"), "w")
    with open(os.path.join(REPO, "data", "experiments", "redis-truncated-wait-time", "raw", "runs.jsonl"), "w") as out:
        rep_id = 0
        for hz in (10, 100):
            order = []
            for rep in range(a.reps):
                arms = ["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"]
                order += [(rep_id + rep, x) for x in arms]
            order.append((rep_id + a.reps, "buggy"))
            rep_id += a.reps + 1
            for rep, arm in order:
                rec = one(arm, hz, a.idle, log)
                rec["rep"] = rep
                out.write(json.dumps(rec) + "\n")
                out.flush()
                print(hz, rep, arm, f"cpu {rec['cpu_pct']:.2f}%", f"peak {rec['peak_rss_mb']} MB", flush=True)


if __name__ == "__main__":
    main()

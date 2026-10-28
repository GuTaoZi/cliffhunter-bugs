#!/usr/bin/env python3
"""memcached/zero-stuck-backoff: buggy parent vs fix, idle server CPU.

Bug: in lru_maintainer_thread() (items.c), an idle slab class grows its sleep with
`backoff += backoff / 8`; a backoff of 0 stays 0, so the next juggle is due immediately and the
thread never sleeps. Fixed by 675d89d784df ("fix lru thread sleeper more"), which seeds a zero
backoff at MIN_LRU_MAINTAINER_SLEEP.

Each run: fresh server (-m 64 -t 4 -o modern), 2,000 items over four size classes, 3 s settle,
then IDLE_S seconds with no client activity, measured with tools/reproduce/measure.py (whole process: all
threads), plus the change in the lru_maintainer_juggles counter. Arms alternate order each
repetition; the first arm is repeated at the end as a drift control.

    python3 bugs/systems/memcached/zero-stuck-backoff/repro/run.py [--reps 5] [--idle 30]
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
from mcclient import MC, start  # noqa: E402

BUILD = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs")) + "/build"
ARMS = {"buggy": f"{BUILD}/memcached-79e35287df4c/src/memcached",
        "fixed": f"{BUILD}/memcached-675d89d784df/src/memcached"}
PORT = 15401


def one(arm, idle_s, log):
    p = start(ARMS[arm], PORT, ["-m", "64", "-t", "4", "-o", "modern"], log)
    try:
        c = MC(PORT)
        for size in (100, 1000, 10000, 100000):
            c.set_many([(f"k{size}-{i}", b"v" * size) for i in range(500)])
        time.sleep(3)
        j0 = int(c.stats()["lru_maintainer_juggles"])
        m = subprocess.run([sys.executable, os.path.join(REPO, "tools", "reproduce", "measure.py"), "--pid", str(p.pid),
                            "--seconds", str(idle_s)], capture_output=True, text=True)
        rec = json.loads(m.stdout)
        j1 = int(c.stats()["lru_maintainer_juggles"])
        rec.update({"arm": arm, "juggles": j1 - j0, "juggles_per_s": (j1 - j0) / rec["wall_s"],
                    "cpu_pct": 100 * rec["cpu_s"] / rec["wall_s"]})
        return rec
    finally:
        p.terminate()
        p.wait(timeout=10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--idle", type=float, default=30)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "memcached-zero-stuck-backoff", "raw"), exist_ok=True)
    log = open(os.path.join(REPO, "data", "experiments", "memcached-zero-stuck-backoff", "raw", "server.log"), "w")
    with open(os.path.join(REPO, "data", "experiments", "memcached-zero-stuck-backoff", "raw", "runs.jsonl"), "w") as out:
        order = []
        for rep in range(a.reps):
            arms = ["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"]
            order += [(rep, x) for x in arms]
        order.append((a.reps, "buggy"))                      # drift control
        for rep, arm in order:
            rec = one(arm, a.idle, log)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"cpu {rec['cpu_pct']:.1f}%", f"juggles/s {rec['juggles_per_s']:.0f}",
                  f"peak {rec['peak_rss_mb']} MB", flush=True)


if __name__ == "__main__":
    main()

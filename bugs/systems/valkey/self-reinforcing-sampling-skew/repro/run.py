#!/usr/bin/env python3
"""valkey/self-reinforcing-sampling-skew: buggy parent vs fix, cost of SPOP as a set drains.

Bug (src/hashtable.c hashtableSampleEntries): fair random selection scans from ONE random cursor
until it has enough samples, so buckets just after a run of empty buckets are picked more often;
SPOP deletes them, the empty run grows, and each pick scans more empty buckets than the last.
Fixed by 45d03e616421 (2025-05-19), which draws a new random cursor per sampled chain and samples
less in sparse tables.

Each run: fresh server; SADD 1,000,000 members; then SPOP one member at a time (pipelined 1,000
commands per round trip) until 100,000 remain. For every block of 10,000 pops: wall time and the
server's CPU (/proc/<pid>/stat). Peak RSS over the whole run from /proc VmHWM. Runs are capped at
CAP_S seconds of popping. Arms alternate order per repetition; buggy is repeated last.
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

ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
TICK = os.sysconf("SC_CLK_TCK")


def build_path(rev):
    sha = subprocess.run(["git", "-C", f"{ROOT}/src/valkey", "rev-parse", rev], capture_output=True,
                         text=True, check=True).stdout.strip()
    return f"{ROOT}/build/valkey-{sha[:12]}/src/src/valkey-server"


ARMS = {"buggy": build_path("45d03e616421~1"), "fixed": build_path("45d03e616421")}
PORT = 15421
N, LEFT, BLOCK, PIPE = 1_000_000, 100_000, 10_000, 1_000


def cpu_s(pid):
    s = open(f"/proc/{pid}/stat").read()
    f = s[s.rindex(")") + 2:].split()
    return (int(f[11]) + int(f[12])) / TICK


def hwm_mb(pid):
    return next(int(l.split()[1]) for l in open(f"/proc/{pid}/status") if l.startswith("VmHWM:")) / 1024


def one(arm, cap_s, log):
    p = start(ARMS[arm], PORT, [], log)
    try:
        r = Resp(PORT)
        for i in range(0, N, 1000):
            r.cmd("SADD", "s", *[f"m{j}" for j in range(i, i + 1000)])
        assert r.cmd("SCARD", "s") == N
        blocks, popped, t_start = [], 0, time.time()
        while popped < N - LEFT and time.time() - t_start < cap_s:
            c0, t0 = cpu_s(p.pid), time.time()
            for _ in range(BLOCK // PIPE):
                res = r.send([["SPOP", "s"]] * PIPE)
                assert all(x is not None for x in res)
            popped += BLOCK
            blocks.append({"popped": popped, "wall_s": time.time() - t0, "cpu_s": cpu_s(p.pid) - c0})
        return {"arm": arm, "blocks": blocks, "popped": popped, "finished": popped >= N - LEFT,
                "pop_wall_s": sum(b["wall_s"] for b in blocks), "pop_cpu_s": sum(b["cpu_s"] for b in blocks),
                "first_block_ms": 1000 * blocks[0]["wall_s"], "last_block_ms": 1000 * blocks[-1]["wall_s"],
                "max_block_ms": 1000 * max(b["wall_s"] for b in blocks), "peak_rss_mb": hwm_mb(p.pid),
                "server": r.info("server").get("valkey_version")}
    finally:
        stop(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--cap", type=float, default=300)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "data", "experiments", "valkey-self-reinforcing-sampling-skew", "raw"), exist_ok=True)
    log = open(os.path.join(REPO, "data", "experiments", "valkey-self-reinforcing-sampling-skew", "raw", "server.log"), "w")
    order = []
    for rep in range(a.reps):
        order += [(rep, x) for x in (["buggy", "fixed"] if rep % 2 == 0 else ["fixed", "buggy"])]
    order.append((a.reps, "buggy"))
    with open(os.path.join(REPO, "data", "experiments", "valkey-self-reinforcing-sampling-skew", "raw", "runs.jsonl"), "w") as out:
        for rep, arm in order:
            rec = one(arm, a.cap, log)
            rec["rep"] = rep
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(rep, arm, f"popped {rec['popped']}", f"wall {rec['pop_wall_s']:.1f}s", f"cpu {rec['pop_cpu_s']:.1f}s",
                  f"first {rec['first_block_ms']:.0f}ms last {rec['last_block_ms']:.0f}ms", f"peak {rec['peak_rss_mb']:.0f}MB", flush=True)


if __name__ == "__main__":
    main()

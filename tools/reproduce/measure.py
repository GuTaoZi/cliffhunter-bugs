#!/usr/bin/env python3
"""Measure a server's CPU time and peak memory over an interval, from /proc.

    tools/reproduce/measure.py --pid N  -- CMD...     run CMD (the workload); measure the server while it runs
    tools/reproduce/measure.py --port P -- CMD...     find the server by its listening TCP port
    tools/reproduce/measure.py --pid N --seconds S    measure for S seconds

Prints one JSON line: wall_s, cpu_s (the server and all its descendants, all threads, including
processes that exit during the interval), peak_rss_mb (largest VmHWM of any process in the tree,
after resetting each process's high-water mark at the start, so it is the interval's own peak),
polls, and the workload's exit code. Exits 2 if no server is found: an absent server must never
read as a zero measurement.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

TICK = os.sysconf("SC_CLK_TCK")


def pid_on_port(port):
    want = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for ln in open(table).read().splitlines()[1:]:
                f = ln.split()
                if f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port:
                    want.add(f"socket:[{f[9]}]")
        except OSError:
            pass
    hits = []
    for d in filter(str.isdigit, os.listdir("/proc")):
        try:
            if any(os.readlink(f"/proc/{d}/fd/{x}") in want for x in os.listdir(f"/proc/{d}/fd")):
                hits.append(int(d))
        except OSError:
            pass
    return min(hits) if hits else None


def tree(pid):
    out = [pid]
    try:
        for k in open(f"/proc/{pid}/task/{pid}/children").read().split():
            out += tree(int(k))
    except OSError:
        pass
    return out


def ticks(pid):
    try:
        s = open(f"/proc/{pid}/stat").read()
        f = s[s.rindex(")") + 2:].split()
        return int(f[11]) + int(f[12])
    except (OSError, ValueError, IndexError):
        return None


def hwm_kb(pid):
    try:
        for ln in open(f"/proc/{pid}/status"):
            if ln.startswith("VmHWM:"):
                return int(ln.split()[1])
    except OSError:
        pass
    return 0


class Sampler(threading.Thread):
    def __init__(self, root):
        super().__init__(daemon=True)
        self.root, self.stop, self.n = root, threading.Event(), 0
        self.first, self.last, self.peak = {}, {}, 0

    def poll(self):
        for p in tree(self.root):
            t = ticks(p)
            if t is None:
                continue
            self.first.setdefault(p, t)
            self.last[p] = max(t, self.last.get(p, 0))
            self.peak = max(self.peak, hwm_kb(p))
        self.n += 1

    def run(self):
        while not self.stop.is_set():
            self.poll()
            self.stop.wait(0.02)

    def cpu_s(self):
        return sum(self.last[p] - self.first[p] for p in self.last) / TICK


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pid", type=int)
    g.add_argument("--port", type=int)
    ap.add_argument("--seconds", type=float)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    root = a.pid or pid_on_port(a.port)
    if not root or not os.path.exists(f"/proc/{root}"):
        print(f"measure: no server found ({'pid' if a.pid else 'port'} {a.pid or a.port})", file=sys.stderr)
        return 2
    for p in tree(root):                       # make VmHWM the interval's own peak
        try:
            open(f"/proc/{p}/clear_refs", "w").write("5")
        except OSError:
            pass
    s = Sampler(root)
    s.poll()
    s.start()
    t0 = time.time()
    rc = subprocess.run(cmd).returncode if cmd else (time.sleep(a.seconds or 1.0) or 0)
    wall = time.time() - t0
    s.stop.set()
    s.join(timeout=2)
    s.poll()
    print(json.dumps({"wall_s": round(wall, 4), "cpu_s": round(s.cpu_s(), 3),
                      "peak_rss_mb": round(s.peak / 1024, 1), "polls": s.n, "root_pid": root,
                      "workload_exit": rc}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

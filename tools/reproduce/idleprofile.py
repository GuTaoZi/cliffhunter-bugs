#!/usr/bin/env python3
"""Per-thread CPU and wakeups of a process tree over a window, from /proc (no tracing).

    tools/reproduce/idleprofile.py --pid N [--seconds S]      prints one JSON object

For every thread of the process and its descendants: thread name, process command line (which
names PostgreSQL's background processes), CPU seconds (utime+stime), voluntary
context switches (each is one sleep that ended, i.e. a wakeup) and involuntary ones, over the
window. Also totals and the tree's peak RSS (VmHWM after a clear_refs reset, as tools/reproduce/measure.py).
Threads that start or exit during the window are counted from when they are first or last seen.
"""
import argparse
import json
import os
import time

TICK = os.sysconf("SC_CLK_TCK")


def tree(root):
    kids = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                ppid = int(open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError):
                continue
            kids.setdefault(ppid, []).append(int(p))
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def threads(pids):
    snap = {}
    for p in pids:
        try:
            tids = os.listdir(f"/proc/{p}/task")
        except OSError:
            continue
        for t in tids:
            try:
                stat = open(f"/proc/{p}/task/{t}/stat").read()
                st = {l.split(":")[0]: l.split(":", 1)[1].strip()
                      for l in open(f"/proc/{p}/task/{t}/status")}
            except OSError:
                continue
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            try:
                cmd = open(f"/proc/{p}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                cmd = ""
            f = stat.rsplit(")", 1)[1].split()
            snap[(p, int(t))] = {"name": name, "cmd": cmd.strip()[:60], "cpu": (int(f[11]) + int(f[12])) / TICK,
                                 "vol": int(st["voluntary_ctxt_switches"]),
                                 "invol": int(st["nonvoluntary_ctxt_switches"])}
    return snap


def hwm(pids):
    total = 0
    for p in pids:
        try:
            for l in open(f"/proc/{p}/status"):
                if l.startswith("VmHWM:"):
                    total += int(l.split()[1])
        except OSError:
            pass
    return total / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--seconds", type=float, default=30)
    a = ap.parse_args()
    pids = tree(a.pid)
    for p in pids:
        try:
            open(f"/proc/{p}/clear_refs", "w").write("5")
        except OSError:
            pass
    t0, s0 = time.time(), threads(pids)
    time.sleep(a.seconds)
    pids = tree(a.pid)
    t1, s1 = time.time(), threads(pids)
    wall = t1 - t0
    rows = []
    for k in set(s0) | set(s1):
        b, e = s0.get(k), s1.get(k)
        if e is None:
            continue
        b = b or {"cpu": 0, "vol": 0, "invol": 0}
        rows.append({"pid": k[0], "tid": k[1], "name": e["name"], "cmd": e["cmd"],
                     "cpu_s": round(e["cpu"] - b["cpu"], 3),
                     "wakeups_per_s": round((e["vol"] - b["vol"]) / wall, 2),
                     "invol_per_s": round((e["invol"] - b["invol"]) / wall, 2)})
    rows.sort(key=lambda r: (-r["wakeups_per_s"], -r["cpu_s"]))
    print(json.dumps({"wall_s": round(wall, 3), "threads": len(rows),
                      "cpu_s": round(sum(r["cpu_s"] for r in rows), 3),
                      "cpu_pct": round(100 * sum(r["cpu_s"] for r in rows) / wall, 3),
                      "wakeups_per_s": round(sum(r["wakeups_per_s"] for r in rows), 2),
                      "peak_rss_mb": round(hwm(pids), 1), "per_thread": rows}))


if __name__ == "__main__":
    main()

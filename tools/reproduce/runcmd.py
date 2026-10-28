#!/usr/bin/env python3
"""Run a self-contained benchmark command; report its own wall time, CPU and peak memory.

    tools/reproduce/runcmd.py OUTFILE -- CMD...

The command's stdout+stderr go to OUTFILE. Prints one JSON line: wall_s, cpu_s (user+sys of the
command and its children, from getrusage), peak_rss_mb (ru_maxrss of the largest child), exit.
"""
import json
import resource
import subprocess
import sys
import time

out, cmd = sys.argv[1], sys.argv[3:] if sys.argv[2] == "--" else sys.argv[2:]
r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
t0 = time.time()
with open(out, "w") as f:
    rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode
wall = time.time() - t0
r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
print(json.dumps({"wall_s": round(wall, 3),
                  "cpu_s": round((r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime), 3),
                  "peak_rss_mb": round(r1.ru_maxrss / 1024, 1), "exit": rc}))

#!/usr/bin/env python3
"""perf script -F comm,tid,ip,sym (stdin) -> folded stacks, outermost first, one 'frame;frame;... count' per line
(the input of flamegraph.pl and speedscope). Thread names are kept as the first frame."""
import collections
import re
import sys

stacks = collections.Counter()
cur, comm = [], None
for line in sys.stdin:
    s = line.rstrip("\n")
    if not s.strip():
        if comm is not None:
            stacks[";".join([comm] + cur[::-1])] += 1
        cur, comm = [], None
        continue
    if not s.startswith((" ", "\t")):
        comm = re.sub(r"\d+$", "", s.split()[0])  # conn12 and conn13 are one thread kind
        continue
    parts = s.split(None, 1)
    cur.append(parts[1].split(" (")[0] if len(parts) > 1 else parts[0])
if comm is not None:
    stacks[";".join([comm] + cur[::-1])] += 1
for k, n in stacks.most_common():
    print(k, n)

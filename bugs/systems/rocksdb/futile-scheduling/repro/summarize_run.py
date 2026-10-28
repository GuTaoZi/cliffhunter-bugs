#!/usr/bin/env python3
"""summarize_run.py OUT LOG SHA TAG RC ARGS -> one JSON line: the driver's JSON plus counts of
info-log lines inside the measured window (between CH_MEASURE_START and CH_MEASURE_END)."""
import json
import sys

out, logp, sha, tag, rc, args = sys.argv[1:7]
try:
    d = json.loads(open(out).read().strip().splitlines()[-1])
except Exception as e:  # noqa: BLE001
    d = {"error": f"no driver output: {e}"}
counts = {"nothing_to_do": 0, "flush_lines": 0, "log_lines": 0}
inside = False
try:
    for ln in open(logp, errors="replace"):
        if "CH_MEASURE_START" in ln:
            inside = True
            continue
        if "CH_MEASURE_END" in ln:
            inside = False
            continue
        if not inside:
            continue
        counts["log_lines"] += 1
        if "Compaction nothing to do" in ln:
            counts["nothing_to_do"] += 1
        if '"event": "flush_finished"' in ln:
            counts["flush_lines"] += 1
except OSError as e:
    counts["error"] = str(e)
d.update({"sha": sha, "tag": tag, "rc": int(rc), "args": args, "log": counts})
print(json.dumps(d))

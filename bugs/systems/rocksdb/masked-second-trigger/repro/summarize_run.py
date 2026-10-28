#!/usr/bin/env python3
"""Merge the driver's JSON line with decision counts from the RocksDB info LOG.

    summarize_run.py results/TAG SHA TAG RC FLAGS   -> results/TAG.json (and prints it)
"""
import json
import re
import sys

base, sha, tag, rc, flags = sys.argv[1:6]
try:
    r = json.loads(open(base + ".out").read().strip().splitlines()[-1])
except Exception as e:  # noqa: BLE001
    r = {"parse_error": str(e)}
try:
    log = open(base + ".LOG", errors="replace").read()
except OSError:
    log = ""
fl = [int(m) for m in re.findall(r'"event": "flush_started".*?"memory_usage": (\d+)', log)]
r.update(
    arm=sha, tag=tag, exit=int(rc), flags=flags,
    # WAL branch, the one that did work (MaybeFlushColumnFamilies past its early return)
    log_wal_branch_flushes=log.count("Flushing all column families with data in WAL number"),
    # memory branch (write_buffer_manager_->ShouldFlush() true)
    log_mem_branch_flushes=log.count("Flushing column family with largest mem table size"),
    log_stop_writes=log.count("Stopping writes because we have"),
    log_slowdown_writes=log.count("Stalling writes because we have"),
    flushes_started=len(fl),
    flushed_memtable_mb_mean=round(sum(fl) / len(fl) / 1048576, 2) if fl else 0.0,
)
# Time series: how long the memory check would have fired (active memtables >= db_write_buffer_size,
# the quantity WriteBufferManager counts: MarkImmutable() frees a memtable's reservation), and the
# total memtable bytes at fixed times.
try:
    rows = [ln.split(",") for ln in open(base + ".csv").read().splitlines()[1:]]
    rows = [(float(a[0]), int(a[1]), int(a[2]), int(a[3])) for a in rows if len(a) >= 6]
    lim = r.get("db_write_buffer_mb", 64.0) * 1048576
    r["frac_samples_active_ge_limit"] = round(sum(1 for x in rows if x[2] >= lim) / len(rows), 3)
    for t in (10, 30, 60, 90, 120, 180):
        near = [x for x in rows if abs(x[0] - t) <= 0.15]
        if near:
            r[f"memtables_mb_at_{t}s"] = round(near[0][1] / 1048576, 1)
except Exception as e:  # noqa: BLE001
    r["csv_error"] = str(e)
open(base + ".json", "w").write(json.dumps(r) + "\n")
print(json.dumps(r))

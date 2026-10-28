"""Run RocksDB's db_bench once and parse what it prints, for the RocksDB reproductions.

    from dbbench import run
    rec = run(db_bench, args, out_txt, db_dir, timeout_s=None, log_patterns={"stalls": r"Stalling writes"})

Each run gets a fresh DB directory (removed afterwards; its LOG is kept next to out_txt) and is measured by
tools/reproduce/runcmd.py (wall, CPU, peak RSS of db_bench itself). Parsed from the output: each benchmark's
micros/op and ops/sec and the latency histogram printed after it (count, average, max, P50 to P99.99), the last
"Cumulative stall" line (seconds and percent, from the stats benchmark), rocksdb.stall.micros (with --statistics),
and the per-second throughput file (--report_file). log_patterns counts regex matches in the DB's LOG.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def num(pat, txt, cast=float, last=False):
    m = re.findall(pat, txt)
    if not m:
        return None
    return cast(m[-1] if last else m[0])


def parse(txt):
    """Per benchmark NAME: NAME_us_per_op, NAME_ops_per_s, and from the histogram printed after it (--histogram=1)
    NAME_count, NAME_avg_us, NAME_max_us and NAME_p50_us to NAME_p9999_us."""
    r = {}
    marks = list(re.finditer(r"^(\w+)\s*:\s*([\d.]+) micros/op (\d+) ops/sec", txt, re.M))
    for i, m in enumerate(marks):
        name = m.group(1)
        r[f"{name}_us_per_op"], r[f"{name}_ops_per_s"] = float(m.group(2)), int(m.group(3))
        t = txt[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(txt)]
        if "Microseconds per " not in t:
            continue
        t = t.split("Microseconds per ", 1)[1]
        r[f"{name}_count"] = num(r"Count: (\d+)", t, int)
        r[f"{name}_avg_us"] = num(r"Average: ([\d.]+)", t)
        r[f"{name}_max_us"] = num(r"Max: ([\d.]+)", t)
        for p in ("P50", "P75", "P99", "P99.9", "P99.99"):
            r[f"{name}_{p.lower().replace('.', '')}_us"] = num(rf"{re.escape(p)}: ([\d.]+)", t)
    m = re.findall(r"Cumulative stall: (\d+):(\d+):([\d.]+) H:M:S, ([\d.]+) percent", txt)
    if m:
        hh, mm, ss, pc = m[-1]
        r["cum_stall_s"], r["cum_stall_pct"] = int(hh) * 3600 + int(mm) * 60 + float(ss), float(pc)
    r["stall_micros"] = num(r"rocksdb\.stall\.micros COUNT : (\d+)", txt, int)
    return r


def per_second(path):
    """(seconds, ops) rows of db_bench's --report_file, and a summary of them. sec_under_5pct counts seconds below 5%
    of the run's own median, so it is not comparable across arms whose medians differ; sec_under_10k counts seconds
    with fewer than 10,000 operations."""
    rows = []
    if os.path.exists(path):
        for line in open(path).read().splitlines()[1:]:
            a = line.split(",")
            if len(a) >= 2:
                rows.append((float(a[0]), float(a[1])))
    v = sorted(x[1] for x in rows)
    med = v[len(v) // 2] if v else 0
    low = [x[1] < 0.05 * med for x in rows]
    run = best = 0
    for b in low:
        run = run + 1 if b else 0
        best = max(best, run)
    return rows, {"sec_n": len(rows), "sec_ops_p5": v[int(0.05 * len(v))] if v else None, "sec_ops_p50": med,
                  "sec_under_5pct": sum(low), "sec_under_5pct_longest": best,
                  "sec_under_10k": sum(1 for x in rows if x[1] < 10_000)}


def run(binary, args, out_txt, db_dir, timeout_s=None, log_patterns=None):
    shutil.rmtree(db_dir, ignore_errors=True)
    os.makedirs(db_dir)
    csv = out_txt[:-4] + "-ops.csv"
    cmd = [sys.executable, os.path.join(HERE, "runcmd.py"), out_txt, "--"]
    if timeout_s:
        cmd += ["timeout", str(timeout_s)]
    cmd += [binary, f"--db={db_dir}/db", "--use_existing_db=0", *args, f"--report_file={csv}"]
    m = subprocess.run(cmd, capture_output=True, text=True)
    rec = json.loads(m.stdout)
    txt = open(out_txt, errors="replace").read()
    rec.update(parse(txt))
    rows, s = per_second(csv)
    rec.update(s)
    log = f"{db_dir}/db/LOG"
    if os.path.exists(log):
        lt = open(log, errors="replace").read()
        for k, pat in (log_patterns or {}).items():
            rec[f"log_{k}"] = len(re.findall(pat, lt))
        shutil.copy(log, out_txt[:-4] + "-LOG")
    rec["timed_out"] = rec.get("exit") == 124
    shutil.rmtree(db_dir, ignore_errors=True)
    return rec

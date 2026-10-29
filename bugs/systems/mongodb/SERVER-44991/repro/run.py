#!/usr/bin/env python3
"""SERVER-44991 (WiredTiger WT-5319): reconciliation rebuilds every prefix-compressed key.

Bug (src/include/btree.i:841-844 at 33204938da7b, __wt_row_leaf_key_info): for a key that is a cell on the page (no
instantiated key) the function clears the caller's data and size outputs. Reconciliation of a row-store leaf passes
its saved previous key there (src/reconcile/rec_row.c:922: &tmpkey->data, &tmpkey->size), so tmpkey->size is 0 when
the fast path tests it (rec_row.c:928, tmpkey->size >= kpack->prefix: append the suffix to the previous key) and every
prefix-compressed key is rebuilt from the closest instantiated key instead (__wt_row_leaf_key_copy, rec_row.c:947;
keys are instantiated every key_gap=10 slots). Fixed in 99636a29c679 (2019-12-14, "WT-5319 Avoid clearing the saved
last-key when no instantiated key"), which deletes the clearing. Parent 33204938da7b.

The trigger is a prefix-compressed row store whose leaf pages were read from disk, then modified and reconciled:
every key on such a page is a cell. wt5319.c (compiled here against each arm's own library and header) loads N
zero-padded keys of KEYW digits (neighbours share a long prefix) with prefix_compression=true, checkpoints and closes;
then two workloads on the reopened table:
  ckpt   ROUNDS rounds of: update every STRIDE-th key (every leaf page dirty), then a timed checkpoint, which
         reconciles every leaf page; the checkpoint call's latency is the measure;
  evict  THREADS threads update random keys for SECS in a SMALL_MB cache, so application threads evict and reconcile
         pages inside their updates; per-update latency (p50, p99, p99.9, max) is the measure.
Each step runs through tools/reproduce/runcmd.py (wall, CPU, peak RSS). Arms alternate per repetition; each
repetition of each arm loads a fresh home under homes/ (homes are kept, not deleted).

    run.py measure [REPS] [disk|mem] | report
"""
import json
import os
import re
import statistics as st
import subprocess
import sys
import time

D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))
REPO = os.path.normpath(os.path.join(D, "../../../../.."))   # bugs/systems/<system>/<bug>/repro/ in the repo
if not os.path.isdir(f"{REPO}/tools/reproduce"):            # a scratch copy: CLIFF_REPO names the repo
    REPO = os.environ["CLIFF_REPO"]
ARMS = {"parent": "33204938da7b", "fix": "99636a29c679"}
ENV = {"N": os.environ.get("N", "2000000"), "KEYW": "32", "VAL": "100", "STRIDE": "64", "ROUNDS": "5",
       "CACHE_MB": "1024", "SMALL_MB": os.environ.get("SMALL_MB", "64"), "THREADS": "8", "SECS": "30"}
# Cells. disk: a fresh home per repetition on disk; each checkpoint writes and syncs about 270 MB, which the first
# runs showed swamps the reconciliation cost. mem: homes on tmpfs and 16-byte values, so key building dominates the
# work per page; one load per arm, reused (every run reopens the table, so its pages are read back cold).
CELLS = {"disk": {"VAL": "100", "base": None}, "mem": {"VAL": "16", "base": "/dev/shm"}}


def binary(arm):
    b = f"{ROOT}/build/wiredtiger-{ARMS[arm]}/src"
    out = f"{D}/wt5319-{ARMS[arm]}"
    subprocess.run(["sh", f"{REPO}/tools/reproduce/inenv.sh", "gcc",
                    f"gcc -O2 -g -std=gnu11 -I{b} -o {out} {D}/wt5319.c {b}/.libs/libwiredtiger.a -lrt -ldl -lpthread -lm"],
                   check=True, capture_output=True)
    return out


def step(exe, home, mode, out):
    env = dict(os.environ, **ENV)
    m = subprocess.run([sys.executable, f"{REPO}/tools/reproduce/runcmd.py", out, "--", exe, home, mode],
                       capture_output=True, text=True, env=env)
    rec = json.loads(m.stdout)
    text = open(out).read()
    st_ = re.search(r"stat rec_pages (\d+) rec_pages_eviction (\d+) application_evict_time_us (\d+) "
                    r"checkpoint_time_recent_ms (\d+) cache_bytes_inuse (\d+)", text)
    if st_:
        rec.update(dict(zip(("rec_pages", "rec_pages_eviction", "app_evict_us", "ckpt_recent_ms", "cache_bytes"),
                            map(int, st_.groups()))))
    return rec, text


HOMES = {}


def one(arm, rep, exe, cell="disk"):
    tag = f"{arm}-r{rep}" if cell == "disk" else f"{cell}-{arm}-r{rep}"
    row = {"arm": arm, "sha": ARMS[arm], "rep": rep, "cell": cell, **{k.lower(): v for k, v in ENV.items()}}
    if CELLS[cell]["base"] is None or arm not in HOMES:
        home = f"{CELLS[cell]['base'] or D + '/homes'}/ch-wt5319-{tag}-{int(time.time())}"
        os.makedirs(home)
        load, text = step(exe, home, "load", f"{D}/data/{tag}-load.txt")
        row.update({f"load_{k}": v for k, v in load.items()})
        if CELLS[cell]["base"] is not None:
            HOMES[arm] = home
    else:
        home = HOMES[arm]
    row["home"] = home
    ck, text = step(exe, home, "ckpt", f"{D}/data/{tag}-ckpt.txt")
    ms = [float(x) for x in re.findall(r"checkpoint_ms ([\d.]+)", text)]
    row.update({f"ckpt_{k}": v for k, v in ck.items()})
    row.update({"ckpt_ms_rounds": ms, "ckpt_ms_mean": st.mean(ms) if ms else None,
                "ckpt_ms_warm": st.mean(ms[1:]) if len(ms) > 1 else None, "ckpt_ms_max": max(ms) if ms else None})
    ev, text = step(exe, home, "evict", f"{D}/data/{tag}-evict.txt")
    m = re.search(r"updates (\d+) per_s ([\d.]+) p50_us ([\d.]+) p99_us ([\d.]+) p999_us ([\d.]+) max_us ([\d.]+)", text)
    row.update({f"evict_{k}": v for k, v in ev.items()})
    if m:
        row.update(dict(zip(("evict_updates", "evict_per_s", "evict_p50_us", "evict_p99_us", "evict_p999_us",
                             "evict_max_us"), map(float, m.groups()))))
    return row


SHOW = ("arm", "rep", "ckpt_ms_warm", "ckpt_ms_max", "ckpt_cpu_s", "ckpt_peak_rss_mb", "evict_per_s", "evict_p99_us",
        "evict_p999_us", "evict_max_us", "evict_app_evict_us", "evict_cpu_s", "evict_peak_rss_mb")


def measure(reps, cell="disk"):
    os.makedirs(f"{D}/data", exist_ok=True)
    ENV["VAL"] = CELLS[cell]["VAL"]
    exe = {a: binary(a) for a in ARMS}
    with open(f"{D}/data/runs.jsonl", "a") as f:
        for rep in range(1, reps + 1):
            for arm in (["parent", "fix"] if rep % 2 else ["fix", "parent"]):
                row = one(arm, rep, exe[arm], cell)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(json.dumps({k: row.get(k) for k in SHOW}), flush=True)


def table(rows, keys):
    out = ["| metric | parent | fix | parent / fix |", "|---|---|---|---|"]
    for k in keys:
        cells, means = [], {}
        for arm in ("parent", "fix"):
            v = [float(r[k]) for r in rows if r["arm"] == arm and r.get(k) is not None]
            if not v:
                cells.append("n/a")
                means[arm] = None
                continue
            means[arm] = st.mean(v)
            cells.append(f"{st.mean(v):.4g} sd {st.pstdev(v):.2g} [{min(v):.4g}, {max(v):.4g}] (n={len(v)})")
        ratio = (f"{means['parent'] / means['fix']:.2f}" if means["parent"] is not None and means["fix"] else "")
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {ratio} |")
    return out


def report():
    rows = [json.loads(l) for l in open(f"{D}/data/runs.jsonl")]
    r0 = rows[0]
    keys = ["ckpt_ms_warm", "ckpt_ms_mean", "ckpt_ms_max", "ckpt_rec_pages", "ckpt_wall_s", "ckpt_cpu_s",
            "ckpt_peak_rss_mb", "evict_per_s", "evict_p50_us", "evict_p99_us", "evict_p999_us", "evict_max_us",
            "evict_app_evict_us", "evict_rec_pages_eviction", "evict_cpu_s", "evict_peak_rss_mb", "load_wall_s",
            "load_cpu_s"]
    out = [f"# SERVER-44991 (WiredTiger WT-5319): parent {ARMS['parent']} vs fix {ARMS['fix']}", "",
           f"Keys of {r0['keyw']} zero-padded digits, prefix_compression=true, "
           f"32 KB leaf pages; reopened after a checkpoint, so every key on a page read back is a cell. ckpt: "
           f"{r0['rounds']} rounds of one update per {r0['stride']} keys, then a timed checkpoint (ckpt_ms_warm: mean "
           f"of rounds 2-{r0['rounds']}); evict: {r0['threads']} threads updating random keys for {r0['secs']} s in a "
           f"{r0['small_mb']} MB cache (per-update latency; app_evict_us: WiredTiger's application thread time "
           "evicting). cpu_s, peak_rss_mb: the process (runcmd.py). mean, sd [min, max]. Cells: disk, a fresh home per "
           "repetition on disk (each checkpoint writes and syncs about 270 MB); mem, homes on tmpfs with 16-byte values "
           "(key building dominates), one load per arm reused.", ""]
    for cell in CELLS:
        rs = [r for r in rows if r.get("cell", "disk") == cell]
        if rs:
            out += [f"## Cell {cell}: {int(rs[0]['n']):,} keys, {rs[0]['val']}-byte values", ""] + table(rs, keys) + [""]
    open(f"{D}/results.md", "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    {"measure": lambda: measure(int(sys.argv[2]) if len(sys.argv) > 2 else 5, sys.argv[3] if len(sys.argv) > 3 else "disk"),
     "report": report}[sys.argv[1]]()

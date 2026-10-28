"""A latency probe for a Redis or Valkey server: one connection sends PING every INTERVAL seconds, from its own process.

    from pingprobe import Probe, reset_hwm, thread_cpu_s
    pr = Probe(port, interval=0.001, cpu=3); pr.start(); ...; s = pr.stop()   # s: summary dict, s["rows"]: samples

Each sample is (unix time, raw ms, corrected ms). raw is the PING's round trip. corrected is measured from the time
the PING was due on a fixed schedule (start + k * INTERVAL, never reset when the probe falls behind), so a stall of
S seconds shows as about S / INTERVAL elevated samples rather than one, the coordinated-omission correction: a
closed-loop probe's percentiles would otherwise hide stalls that are rare in sample count but long in time. The
summary reports both series, and counts of raw samples over 10 and 100 ms. The probe runs in a separate process (not
a thread) so that the driver's own work does not delay it; cpu pins it to one core.
"""
import multiprocessing as mp
import os
import socket
import time


def _loop(port, interval, cpu, stop, q):
    if cpu is not None:
        os.sched_setaffinity(0, {cpu})
    s = socket.create_connection(("127.0.0.1", port))
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    rows, due = [], time.perf_counter()
    off = time.time() - time.perf_counter()
    while not stop.is_set():
        now = time.perf_counter()
        if now < due:
            time.sleep(due - now)
        t0 = time.perf_counter()
        s.sendall(b"PING\r\n")
        buf = b""
        while not buf.endswith(b"\r\n"):
            buf += s.recv(64)
        t1 = time.perf_counter()
        rows.append((round(t0 + off, 4), round((t1 - t0) * 1e3, 3), round((t1 - min(due, t0)) * 1e3, 3)))
        due += interval
    s.close()
    q.put(rows)


def pct(v, f):
    return v[min(len(v) - 1, int(f * len(v)))] if v else None


def summary(rows):
    raw = sorted(r[1] for r in rows)
    cor = sorted(r[2] for r in rows)
    out = {"n": len(rows)}
    for name, v in (("raw", raw), ("cor", cor)):
        for f, k in ((0.5, "p50"), (0.99, "p99"), (0.999, "p999")):
            out[f"{name}_{k}_ms"] = pct(v, f)
        out[f"{name}_max_ms"] = v[-1] if v else None
    out["raw_over_10ms"] = sum(1 for x in raw if x > 10)
    out["raw_over_100ms"] = sum(1 for x in raw if x > 100)
    out["blocked_ms"] = round(sum(x - 1 for x in raw if x > 2), 1)   # time the server did not answer, beyond 1 ms
    return out


class Probe:
    def __init__(self, port, interval=0.001, cpu=None):
        self.stop_ev, self.q = mp.Event(), mp.Queue()
        self.p = mp.Process(target=_loop, args=(port, interval, cpu, self.stop_ev, self.q), daemon=True)

    def start(self):
        self.p.start()

    def stop(self):
        self.stop_ev.set()
        rows = self.q.get(timeout=120)
        self.p.join(10)
        s = summary(rows)
        s["rows"] = rows
        return s


def reset_hwm(pid):
    """Make the process's VmHWM (peak RSS) start from its current RSS, so a later read is the interval's own peak."""
    try:
        with open(f"/proc/{pid}/clear_refs", "w") as f:
            f.write("5")
    except OSError:
        pass


def thread_cpu_s(pid, tid=None):
    """CPU seconds (user + system) of one thread; the main thread by default."""
    f = open(f"/proc/{pid}/task/{tid or pid}/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")

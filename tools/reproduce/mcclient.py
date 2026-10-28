"""A minimal memcached text-protocol client (set, get, stats, raw), enough for the experiments."""
import socket
import subprocess
import time


class MC:
    def __init__(self, port, host="127.0.0.1", timeout=10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""

    def _readline(self):
        while b"\r\n" not in self.buf:
            chunk = self.s.recv(1 << 16)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        ln, self.buf = self.buf.split(b"\r\n", 1)
        return ln

    def _readn(self, n):
        while len(self.buf) < n:
            self.buf += self.s.recv(1 << 16)
        v, self.buf = self.buf[:n], self.buf[n:]
        return v

    def set(self, key, value, exptime=0):
        self.s.sendall(b"set %s 0 %d %d\r\n%s\r\n" % (key.encode(), exptime, len(value), value))
        return self._readline()

    def set_many(self, items, exptime=0):
        """Pipelined sets; returns the list of reply lines."""
        self.s.sendall(b"".join(b"set %s 0 %d %d\r\n%s\r\n" % (k.encode(), exptime, len(v), v)
                                for k, v in items))
        return [self._readline() for _ in items]

    def get(self, key):
        self.s.sendall(b"get %s\r\n" % key.encode())
        ln = self._readline()
        if ln == b"END":
            return None
        n = int(ln.split()[3])
        v = self._readn(n + 2)[:-2]
        assert self._readline() == b"END"
        return v

    def stats(self, arg=""):
        self.s.sendall(b"stats %s\r\n" % arg.encode() if arg else b"stats\r\n")
        out = {}
        while True:
            ln = self._readline()
            if ln == b"END":
                return out
            p = ln.decode().split(" ", 2)
            if p[0] == "STAT":
                out[p[1]] = p[2]

    def raw(self, line):
        self.s.sendall(line.encode() + b"\r\n")
        return self._readline()


def start(binary, port, args, log):
    """Start memcached in the foreground on 127.0.0.1:port; wait until it accepts connections."""
    p = subprocess.Popen([binary, "-p", str(port), "-U", "0", "-l", "127.0.0.1", *args],
                         stdout=log, stderr=subprocess.STDOUT)
    for _ in range(200):
        try:
            MC(port, timeout=1).s.close()
            return p
        except OSError:
            if p.poll() is not None:
                raise RuntimeError(f"memcached exited: {p.returncode}")
            time.sleep(0.05)
    p.kill()
    raise RuntimeError("memcached did not start")

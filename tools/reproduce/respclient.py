"""A minimal pipelined RESP client for Redis and Valkey, plus a helper that starts a server."""
import socket
import subprocess
import time


class Resp:
    def __init__(self, port, host="127.0.0.1", timeout=60):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def send(self, cmds):
        """Send a list of commands (each a list of args) pipelined; return their replies."""
        out = []
        for c in cmds:
            out.append(b"*%d\r\n" % len(c))
            for a in c:
                a = a if isinstance(a, bytes) else str(a).encode()
                out.append(b"$%d\r\n%s\r\n" % (len(a), a))
        self.s.sendall(b"".join(out))
        return [self.read() for _ in cmds]

    def cmd(self, *args):
        return self.send([list(args)])[0]

    def _line(self):
        while b"\r\n" not in self.buf:
            chunk = self.s.recv(1 << 20)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        ln, self.buf = self.buf.split(b"\r\n", 1)
        return ln

    def read(self):
        ln = self._line()
        t, rest = ln[:1], ln[1:]
        if t == b"+":
            return rest
        if t == b"-":
            return RuntimeError(rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n < 0:
                return None
            while len(self.buf) < n + 2:
                self.buf += self.s.recv(1 << 20)
            v, self.buf = self.buf[:n], self.buf[n + 2:]
            return v
        if t == b"*":
            n = int(rest)
            return None if n < 0 else [self.read() for _ in range(n)]
        raise RuntimeError(f"unexpected reply {ln[:60]!r}")

    def info(self, section="all"):
        txt = self.cmd("INFO", section).decode()
        return dict(l.split(":", 1) for l in txt.splitlines() if ":" in l and not l.startswith("#"))


def start(binary, port, args, log):
    """Start a redis/valkey server in the foreground on 127.0.0.1:port; wait until it answers PING."""
    p = subprocess.Popen([binary, "--port", str(port), "--bind", "127.0.0.1", "--save", "",
                          "--appendonly", "no", *args], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(400):
        try:
            if Resp(port, timeout=1).cmd("PING") == b"PONG":
                return p
        except OSError:
            if p.poll() is not None:
                raise RuntimeError(f"server exited: {p.returncode}")
            time.sleep(0.05)
    p.kill()
    raise RuntimeError("server did not start")


def stop(p):
    p.terminate()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()

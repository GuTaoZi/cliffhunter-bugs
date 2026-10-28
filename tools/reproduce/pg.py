"""Run a PostgreSQL build from tools/reproduce/build.sh: initdb, start on a port, run SQL with its psql, stop."""
import os
import subprocess
import time

ROOT = os.path.expanduser(os.environ.get("CLIFF_DATA", "~/.cache/cliffhunter-bugs"))


def install_dir(rev):
    sha = subprocess.run(["git", "-C", f"{ROOT}/src/postgres", "rev-parse", rev], capture_output=True,
                         text=True, check=True).stdout.strip()
    return f"{ROOT}/build/postgres-{sha[:12]}/install"


class PG:
    def __init__(self, install, port, datadir):
        self.bin, self.port, self.data = os.path.join(install, "bin"), port, datadir
        self.sock = datadir + ".sock"
        self.proc_pid = None

    def initdb(self):
        if os.path.exists(os.path.join(self.data, "PG_VERSION")):
            return
        os.makedirs(os.path.dirname(self.data), exist_ok=True)
        subprocess.run([f"{self.bin}/initdb", "-D", self.data, "-U", "postgres", "--no-sync"],
                       check=True, capture_output=True)

    def start(self, extra=()):
        os.makedirs(self.sock, exist_ok=True)
        opts = f"-p {self.port} -k {self.sock} -c listen_addresses='' -c fsync=off " + " ".join(extra)
        subprocess.run([f"{self.bin}/pg_ctl", "-D", self.data, "-o", opts, "-l", self.data + ".log", "-w",
                        "start"], check=True, capture_output=True)
        self.proc_pid = int(open(os.path.join(self.data, "postmaster.pid")).readline())

    def stop(self):
        subprocess.run([f"{self.bin}/pg_ctl", "-D", self.data, "-m", "fast", "-w", "stop"], capture_output=True)

    def psql(self, sql, timeout=1800):
        r = subprocess.run([f"{self.bin}/psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", self.sock, "-p", str(self.port),
                            "-U", "postgres", "-d", "postgres", "-At", "-c", sql],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-1000:])
        return r.stdout

    def psql_cmd(self, sql):
        """The argv to run `sql` with this server's psql (for wrapping in tools/reproduce/measure.py)."""
        return [f"{self.bin}/psql", "-X", "-v", "ON_ERROR_STOP=1", "-h", self.sock, "-p", str(self.port),
                "-U", "postgres", "-d", "postgres", "-At", "-c", sql]

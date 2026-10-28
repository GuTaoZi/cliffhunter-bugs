#!/bin/sh
# Check tools/reproduce/measure.py against known work: a process that waits for a signal file, then burns
# 1.0 s of CPU and touches 200 MB. Expected: cpu_s ~1.0, peak_rss_mb >= ~200. Also: a missing
# server must make measure.py exit 2.
set -u
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
python3 -c "
import os, time
while not os.path.exists('$T/go'): time.sleep(0.01)
end = time.process_time() + 1.0
while time.process_time() < end: pass
b = bytearray(200 << 20)
for i in range(0, len(b), 4096): b[i] = 1
time.sleep(0.3)
" &
P=$!
python3 "$D/measure.py" --pid $P -- sh -c "touch $T/go; while kill -0 $P 2>/dev/null; do sleep 0.05; done"
python3 "$D/measure.py" --port 1 --seconds 0.1; echo "missing-server exit=$?"
rm -rf "$T"

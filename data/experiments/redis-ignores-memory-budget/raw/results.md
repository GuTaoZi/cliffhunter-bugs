### A-lru-4M

policy allkeys-lru, N=4194304 keys populated, maxmemory = used_memory + 8 MiB, K=1000000 SETs in batches of 100

**parent** (redis-2f41a3856845), 5 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 11.4 | 1.32 | 9.2 - 12.5 |
| batch latency p50 (ms) | 0.975 | 0.16 | 0.689 - 1.05 |
| batch latency p99 (ms) | 1.51 | 0.197 | 1.16 - 1.61 |
| batch latency max (ms) | 56.6 | 0.538 | 55.7 - 57.1 |
| batches > 10 ms (count) | 15 | 0 | 15 - 15 |
| server CPU over window (s) | 5.02 | 0.0421 | 4.95 - 5.06 |
| server peak RSS over window (MB) | 426.0 | 1.9 | 424.4 - 429.1 |
| measured window wall (s) | 11.9 | 1.32 | 9.79 - 13.1 |
| peak used_memory over maxmemory (MiB) | 54.91 | 0.07 | 54.84 - 55.00 |
| evicted_keys | 1248485 | 25 | 1248466 - 1248529 |
| SETs rejected with OOM | 0 | 0 | 0 - 0 |
| SETs accepted | 1000000 | 0 | 1000000 - 1000000 |
| lowest key count during run | 3839767 | 619 | 3838764 - 3840256 |
| final key count (DBSIZE) | 3945819 | 25 | 3945775 - 3945838 |
| time until used_memory back within maxmemory+1MiB (s) | 0.83 | 0.00597 | 0.824 - 0.836 |
| db0 bucket array(s) before -> after | [4194304] -> ['[8388608]'] | | |

**fix** (redis-75f9dec64455), 5 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 9.83 | 0.823 | 8.5 - 10.6 |
| batch latency p50 (ms) | 0.925 | 0.175 | 0.635 - 1.07 |
| batch latency p99 (ms) | 1.25 | 0.0192 | 1.23 - 1.27 |
| batch latency max (ms) | 2.03 | 0.234 | 1.85 - 2.36 |
| batches > 10 ms (count) | 0 | 0 | 0 - 0 |
| server CPU over window (s) | 4.26 | 0.0241 | 4.23 - 4.29 |
| server peak RSS over window (MB) | 391.5 | 0.1 | 391.3 - 391.6 |
| measured window wall (s) | 10.4 | 0.823 | 9.09 - 11.2 |
| peak used_memory over maxmemory (MiB) | 0.02 | 0.00 | 0.02 - 0.02 |
| evicted_keys | 810084 | 14 | 810066 - 810100 |
| SETs rejected with OOM | 0 | 0 | 0 - 0 |
| SETs accepted | 1000000 | 0 | 1000000 - 1000000 |
| lowest key count during run | 4194304 | 0 | 4194304 - 4194304 |
| final key count (DBSIZE) | 4384220 | 14 | 4384204 - 4384238 |
| db0 bucket array(s) before -> after | [4194304] -> ['[4194304]'] | | |

### B-noevict-4M

policy noeviction, N=4194304 keys populated, maxmemory = used_memory + 8 MiB, K=300000 SETs in batches of 100

**parent** (redis-2f41a3856845), 5 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 1.01 | 0.0769 | 0.965 - 1.15 |
| batch latency p50 (ms) | 0.296 | 0.0293 | 0.28 - 0.348 |
| batch latency p99 (ms) | 0.421 | 0.102 | 0.355 - 0.602 |
| batch latency max (ms) | 2.28 | 0.026 | 2.25 - 2.32 |
| batches > 10 ms (count) | 0 | 0 | 0 - 0 |
| server CPU over window (s) | 0.536 | 0.00548 | 0.53 - 0.54 |
| server peak RSS over window (MB) | 370.5 | 0.3 | 370.1 - 370.8 |
| measured window wall (s) | 11.1 | 0.0767 | 11 - 11.2 |
| peak used_memory over maxmemory (MiB) | 56.08 | 0.00 | 56.08 - 56.08 |
| evicted_keys | 0 | 0 | 0 - 0 |
| SETs rejected with OOM | 299999 | 0 | 299999 - 299999 |
| SETs accepted | 1 | 0 | 1 - 1 |
| lowest key count during run | 4194304 | 0 | 4194304 - 4194304 |
| final key count (DBSIZE) | 4194305 | 0 | 4194305 - 4194305 |
| db0 bucket array(s) before -> after | [4194304] -> ['[4194304, 8388608]'] | | |

**fix** (redis-75f9dec64455), 5 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 1.32 | 0.163 | 1.06 - 1.47 |
| batch latency p50 (ms) | 0.38 | 0.053 | 0.287 - 0.415 |
| batch latency p99 (ms) | 0.508 | 0.0592 | 0.41 - 0.557 |
| batch latency max (ms) | 0.8 | 0.106 | 0.642 - 0.905 |
| batches > 10 ms (count) | 0 | 0 | 0 - 0 |
| server CPU over window (s) | 0.436 | 0.0114 | 0.42 - 0.45 |
| server peak RSS over window (MB) | 365.0 | 0.1 | 364.9 - 365.1 |
| measured window wall (s) | 1.88 | 0.164 | 1.62 - 2.04 |
| peak used_memory over maxmemory (MiB) | 0.04 | 0.00 | 0.04 - 0.04 |
| evicted_keys | 0 | 0 | 0 - 0 |
| SETs rejected with OOM | 184063 | 0 | 184063 - 184063 |
| SETs accepted | 115937 | 0 | 115937 - 115937 |
| lowest key count during run | 4194304 | 0 | 4194304 - 4194304 |
| final key count (DBSIZE) | 4310241 | 0 | 4310241 - 4310241 |
| db0 bucket array(s) before -> after | [4194304] -> ['[4194304]'] | | |

### C-lru-16M

policy allkeys-lru, N=16777216 keys populated, maxmemory = used_memory + 32 MiB, K=3000000 SETs in batches of 100

**parent** (redis-2f41a3856845), 3 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 37.5 | 0.689 | 36.9 - 38.2 |
| batch latency p50 (ms) | 1.07 | 0.00292 | 1.07 - 1.07 |
| batch latency p99 (ms) | 1.68 | 0.0108 | 1.68 - 1.7 |
| batch latency max (ms) | 57.7 | 0.266 | 57.5 - 58 |
| batches > 10 ms (count) | 76 | 1 | 75 - 77 |
| server CPU over window (s) | 17.4 | 0.115 | 17.3 - 17.6 |
| server peak RSS over window (MB) | 1687.7 | 0.4 | 1687.4 - 1688.1 |
| measured window wall (s) | 38.1 | 0.693 | 37.5 - 38.9 |
| peak used_memory over maxmemory (MiB) | 223.07 | 0.00 | 223.06 - 223.07 |
| evicted_keys | 4187535 | 63 | 4187472 - 4187598 |
| SETs rejected with OOM | 0 | 0 | 0 - 0 |
| SETs accepted | 3000000 | 0 | 3000000 - 3000000 |
| lowest key count during run | 15358536 | 1957 | 15356744 - 15360624 |
| final key count (DBSIZE) | 15589681 | 63 | 15589618 - 15589744 |
| time until used_memory back within maxmemory+1MiB (s) | 4.26 | 0.0317 | 4.23 - 4.29 |
| db0 bucket array(s) before -> after | [16777216] -> ['[33554432]'] | | |

**fix** (redis-75f9dec64455), 3 repetitions

| metric | mean | sd | min - max |
|---|---|---|---|
| insert phase wall (s) | 31 | 0.514 | 30.6 - 31.6 |
| batch latency p50 (ms) | 1.1 | 0.00506 | 1.09 - 1.1 |
| batch latency p99 (ms) | 1.28 | 0.00533 | 1.28 - 1.29 |
| batch latency max (ms) | 6.52 | 0.263 | 6.21 - 6.69 |
| batches > 10 ms (count) | 0 | 0 | 0 - 0 |
| server CPU over window (s) | 13.7 | 0.04 | 13.6 - 13.7 |
| server peak RSS over window (MB) | 1479.8 | 0.1 | 1479.7 - 1479.8 |
| measured window wall (s) | 31.7 | 0.514 | 31.2 - 32.2 |
| peak used_memory over maxmemory (MiB) | 0.02 | 0.00 | 0.02 - 0.02 |
| evicted_keys | 2491302 | 16 | 2491292 - 2491321 |
| SETs rejected with OOM | 0 | 0 | 0 - 0 |
| SETs accepted | 3000000 | 0 | 3000000 - 3000000 |
| lowest key count during run | 16777216 | 0 | 16777216 - 16777216 |
| final key count (DBSIZE) | 17285914 | 16 | 17285895 - 17285924 |
| db0 bucket array(s) before -> after | [16777216] -> ['[16777216]'] | | |


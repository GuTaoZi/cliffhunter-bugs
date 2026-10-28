# redis unknown-type-costed-1: parent 43af28f5b487 vs fix 5b0a06af4899

One stream of 3,000,000 entries at stream-node-max-entries 1 (one rax node each), then deleted while a 1 ms PING probe runs on its own core (raw: round trip; cor: from the scheduled send time). del_call_ms: the deleting command's own round trip; free_done_s: until lazyfree_pending_objects is 0. mean, sd [min, max].

## UNLINK

| metric | parent | fix | parent / fix |
|---|---|---|---|
| del_call_ms | 167.8 sd 8.1 [151.6, 173] (n=5) | 0.216 sd 0.026 [0.17, 0.24] (n=5) | 777.02 |
| raw_p50_ms | 0.044 sd 0.0011 [0.043, 0.046] (n=5) | 0.0432 sd 0.0004 [0.043, 0.044] (n=5) | 1.02 |
| raw_p99_ms | 0.091 sd 0.013 [0.084, 0.117] (n=5) | 0.7018 sd 0.34 [0.217, 0.998] (n=5) | 0.13 |
| raw_p999_ms | 1.022 sd 0.043 [0.999, 1.107] (n=5) | 1.203 sd 0.39 [0.999, 1.982] (n=5) | 0.85 |
| raw_max_ms | 167.3 sd 8 [151.3, 172.4] (n=5) | 3.438 sd 0.36 [3.039, 3.95] (n=5) | 48.66 |
| cor_p999_ms | 162.6 sd 8 [146.7, 167.6] (n=5) | 2.984 sd 0.33 [2.453, 3.364] (n=5) | 54.50 |
| cor_max_ms | 167.3 sd 8 [151.4, 172.5] (n=5) | 3.743 sd 0.78 [3.101, 5.229] (n=5) | 44.71 |
| raw_over_10ms | 1 sd 0 [1, 1] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| raw_over_100ms | 1 sd 0 [1, 1] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| blocked_ms | 169.9 sd 9.3 [151.4, 175.9] (n=5) | 5.78 sd 2.3 [3.5, 10] (n=5) | 29.39 |
| free_done_s | 0.0002 sd 0.0004 [0, 0.001] (n=5) | 0.1436 sd 0.02 [0.104, 0.156] (n=5) | 0.00 |
| server_cpu_s | 0.28 sd 0.011 [0.26, 0.29] (n=5) | 0.222 sd 0.0075 [0.21, 0.23] (n=5) | 1.26 |
| main_thread_cpu_s | 0.256 sd 0.008 [0.24, 0.26] (n=5) | 0.094 sd 0.0049 [0.09, 0.1] (n=5) | 2.72 |
| server_peak_rss_mb | 178 sd 0.04 [177.9, 178] (n=5) | 178.1 sd 0.049 [178.1, 178.2] (n=5) | 1.00 |
| used_memory_mb_before | 167.1 sd 0 [167.1, 167.1] (n=5) | 167.1 sd 0.04 [167, 167.1] (n=5) | 1.00 |
| load_s | 4.022 sd 0.019 [4.01, 4.06] (n=5) | 4.056 sd 0.022 [4.02, 4.08] (n=5) | 0.99 |

## DEL (the control: inline in both arms)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| del_call_ms | 172 sd 0.23 [171.7, 172.2] (n=2) | 184.8 sd 11 [173.9, 195.6] (n=2) | 0.93 |
| raw_p50_ms | 0.044 sd 0 [0.044, 0.044] (n=2) | 0.0435 sd 0.0005 [0.043, 0.044] (n=2) | 1.01 |
| raw_p99_ms | 0.4265 sd 0.32 [0.103, 0.75] (n=2) | 0.093 sd 0.001 [0.092, 0.094] (n=2) | 4.59 |
| raw_p999_ms | 1.494 sd 0.49 [1.001, 1.986] (n=2) | 1.002 sd 0.003 [0.999, 1.005] (n=2) | 1.49 |
| raw_max_ms | 171.3 sd 0.11 [171.2, 171.4] (n=2) | 184.2 sd 11 [173, 195.4] (n=2) | 0.93 |
| cor_p999_ms | 166.6 sd 0.2 [166.4, 166.8] (n=2) | 179.5 sd 11 [168.3, 190.7] (n=2) | 0.93 |
| cor_max_ms | 171.3 sd 0.11 [171.2, 171.4] (n=2) | 184.3 sd 11 [173.1, 195.5] (n=2) | 0.93 |
| raw_over_10ms | 1 sd 0 [1, 1] (n=2) | 1 sd 0 [1, 1] (n=2) | 1.00 |
| raw_over_100ms | 1 sd 0 [1, 1] (n=2) | 1 sd 0 [1, 1] (n=2) | 1.00 |
| blocked_ms | 175 sd 0.8 [174.2, 175.8] (n=2) | 186.7 sd 8.8 [177.8, 195.5] (n=2) | 0.94 |
| free_done_s | 0.001 sd 0 [0.001, 0.001] (n=2) | 0 sd 0 [0, 0] (n=2) | inf |
| server_cpu_s | 0.29 sd 0 [0.29, 0.29] (n=2) | 0.295 sd 0.015 [0.28, 0.31] (n=2) | 0.98 |
| main_thread_cpu_s | 0.265 sd 0.005 [0.26, 0.27] (n=2) | 0.275 sd 0.015 [0.26, 0.29] (n=2) | 0.96 |
| server_peak_rss_mb | 178.1 sd 0.05 [178.1, 178.2] (n=2) | 178.1 sd 0 [178.1, 178.1] (n=2) | 1.00 |
| used_memory_mb_before | 167.1 sd 0 [167.1, 167.1] (n=2) | 167.1 sd 0 [167.1, 167.1] (n=2) | 1.00 |
| load_s | 4.025 sd 0.015 [4.01, 4.04] (n=2) | 4.07 sd 0.03 [4.04, 4.1] (n=2) | 0.99 |

parent unlink rep 1: xlen 3000000; `calls=1,usec=171594,usec_per_call=171594.00`; lazyfree_pending_objects (s, n, used_memory) `[[0.0, 0, 959984], [0.051, 0, 959984], [0.101, 0, 919032], [0.151, 0, 959984], [0.201, 0, 959984], [0.252, 0, 959984]]`

fix unlink rep 1: xlen 3000000; `calls=1,usec=20,usec_per_call=20.00`; lazyfree_pending_objects (s, n, used_memory) `[[0.0, 1, 175234920], [0.051, 1, 101706288], [0.102, 1, 23383472], [0.153, 0, 959776], [0.203, 0, 959776], [0.253, 0, 959776]]`

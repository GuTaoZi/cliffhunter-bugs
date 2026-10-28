# rocksdb stall-cannot-help: parent e4609a749be4 vs fix ee027fc19f4a

db_bench fillseq of 80,000 1,000-byte values with auto compaction off and an L0 slowdown trigger of 6 files (delayed_write_rate 1 MB/s), on tmpfs; fillseq_*: db_bench's per-write latency histogram; cum_stall: its stats benchmark. mean, sd [min, max].

## Slowdown (stop trigger out of reach)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| wall_s | 41.31 sd 1.5 [40.53, 44.39] (n=5) | 0.1268 sd 0.0059 [0.119, 0.137] (n=5) | 325.80 |
| fillseq_ops_per_s | 1940 sd 68 [1803, 1974] (n=5) | 7.908e+05 sd 4.1e+04 [7.156e+05, 8.401e+05] (n=5) | 0.00 |
| fillseq_p50_us | 202 sd 4e+02 [1.65, 1003] (n=5) | 0.518 sd 0.012 [0.51, 0.54] (n=5) | 390.02 |
| fillseq_p99_us | 1196 sd 0.15 [1196, 1196] (n=5) | 1.844 sd 0.52 [1.23, 2.81] (n=5) | 648.48 |
| fillseq_p999_us | 1200 sd 0.016 [1200, 1200] (n=5) | 4.946 sd 1.4 [3.17, 7.46] (n=5) | 242.54 |
| fillseq_max_us | 9805 sd 4e+02 [9135, 1.033e+04] (n=5) | 1.014e+04 sd 9.3e+02 [8924, 1.178e+04] (n=5) | 0.97 |
| fillseq_avg_us | 516.1 sd 19 [506.4, 554.5] (n=5) | 1.267 sd 0.07 [1.19, 1.396] (n=5) | 407.20 |
| cum_stall_s | 41.15 sd 1.5 [40.38, 44.19] (n=5) | 0.046 sd 0.013 [0.026, 0.063] (n=5) | 894.52 |
| cum_stall_pct | 99.68 sd 0.04 [99.6, 99.7] (n=5) | 44.94 sd 13 [25.9, 65.3] (n=5) | 2.22 |
| stall_micros | 4.115e+07 sd 1.5e+06 [4.038e+07, 4.419e+07] (n=5) | 4.59e+04 sd 1.2e+04 [2.63e+04, 6.29e+04] (n=5) | 896.41 |
| sec_under_5pct | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stalling_l0 | 24.4 sd 0.8 [24, 26] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stopping_l0 | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| cpu_s | 0.5542 sd 0.036 [0.521, 0.625] (n=5) | 0.1766 sd 0.015 [0.149, 0.192] (n=5) | 3.14 |
| peak_rss_mb | 21.74 sd 0.23 [21.5, 22.1] (n=5) | 21.9 sd 0.32 [21.6, 22.5] (n=5) | 0.99 |

## Stop trigger 10, 60 s timeout

| metric | parent | fix | parent / fix |
|---|---|---|---|
| wall_s | 60 sd 0 [60, 60] (n=1) | 0.125 sd 0 [0.125, 0.125] (n=1) | 480.03 |
| fillseq_ops_per_s | n/a | 8.068e+05 sd 0 [8.068e+05, 8.068e+05] (n=1) |  |
| fillseq_p50_us | n/a | 0.51 sd 0 [0.51, 0.51] (n=1) |  |
| fillseq_p99_us | n/a | 1.74 sd 0 [1.74, 1.74] (n=1) |  |
| fillseq_p999_us | n/a | 4.6 sd 0 [4.6, 4.6] (n=1) |  |
| fillseq_max_us | n/a | 9699 sd 0 [9699, 9699] (n=1) |  |
| fillseq_avg_us | n/a | 1.238 sd 0 [1.238, 1.238] (n=1) |  |
| cum_stall_s | n/a | 0.044 sd 0 [0.044, 0.044] (n=1) |  |
| cum_stall_pct | n/a | 43.9 sd 0 [43.9, 43.9] (n=1) |  |
| stall_micros | n/a | 4.4e+04 sd 0 [4.4e+04, 4.4e+04] (n=1) |  |
| sec_under_5pct | 0 sd 0 [0, 0] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| log_stalling_l0 | 7 sd 0 [7, 7] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| log_stopping_l0 | 1 sd 0 [1, 1] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| cpu_s | 0.192 sd 0 [0.192, 0.192] (n=1) | 0.175 sd 0 [0.175, 0.175] (n=1) | 1.10 |
| peak_rss_mb | 21.6 sd 0 [21.6, 21.6] (n=1) | 21.8 sd 0 [21.8, 21.8] (n=1) | 0.99 |

exit codes (124: killed by the timeout): parent r1 124, fix r1 0

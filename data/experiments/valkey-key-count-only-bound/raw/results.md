# valkey key-count-only-bound: parent 3293091659be vs fix 9b270b6d8b1a

300 RESP3 clients each tracking the same 10,000 keys (3,000,000 tracking items), then CONFIG SET tracking-table-max-keys 10 while a 1 ms PING probe runs on its own core (raw: round trip; cor: from the scheduled send time). evict_done_s: until tracking_total_keys is at most 10. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 0.0464 sd 0.0019 [0.045, 0.05] (n=5) | 0.0462 sd 0.0004 [0.046, 0.047] (n=5) | 1.00 |
| raw_p99_ms | 0.0858 sd 0.022 [0.057, 0.112] (n=5) | 2.155 sd 0.033 [2.125, 2.218] (n=5) | 0.04 |
| raw_p999_ms | 83.01 sd 4.6 [77.75, 88.94] (n=5) | 4.191 sd 0.12 [4.085, 4.427] (n=5) | 19.81 |
| raw_max_ms | 319.9 sd 43 [267.2, 357.8] (n=5) | 7.318 sd 0.49 [6.746, 8.216] (n=5) | 43.71 |
| cor_p99_ms | 1020 sd 7.5 [1010, 1033] (n=5) | 765.1 sd 10 [753, 778.4] (n=5) | 1.33 |
| cor_p999_ms | 1055 sd 7.5 [1045, 1068] (n=5) | 779 sd 11 [765.5, 795] (n=5) | 1.35 |
| cor_max_ms | 1058 sd 7.5 [1048, 1071] (n=5) | 780.2 sd 11 [767.1, 796] (n=5) | 1.36 |
| raw_over_10ms | 7.6 sd 0.49 [7, 8] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| raw_over_100ms | 3.8 sd 0.4 [3, 4] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| blocked_ms | 1059 sd 7.4 [1048, 1071] (n=5) | 142.3 sd 9.2 [130.5, 155.1] (n=5) | 7.45 |
| evict_done_s | 1.104 sd 0.046 [1.06, 1.16] (n=5) | 2.656 sd 0.0049 [2.65, 2.66] (n=5) | 0.42 |
| tracking_keys_after | 10 sd 0 [10, 10] (n=5) | 10 sd 0 [10, 10] (n=5) | 1.00 |
| server_cpu_s | 1.13 sd 0.0063 [1.12, 1.14] (n=5) | 2.082 sd 0.017 [2.06, 2.11] (n=5) | 0.54 |
| main_thread_cpu_s | 1.122 sd 0.0098 [1.11, 1.14] (n=5) | 2.068 sd 0.016 [2.05, 2.09] (n=5) | 0.54 |
| server_peak_rss_mb | 191.6 sd 3.3 [185.8, 194.5] (n=5) | 169.4 sd 3.6 [166.1, 174.2] (n=5) | 1.13 |

parent, rep 1: tracking_total_keys over time (s, keys) `[[0.22, 8500], [0.61, 5500], [1.06, 900], [1.16, 10], [1.26, 10], [1.36, 10], [1.46, 10], [1.56, 10], [1.66, 10], [1.76, 10], [1.86, 10], [1.96, 10]]`

fix, rep 1: tracking_total_keys over time (s, keys) `[[0.1, 9927], [0.21, 9643], [0.31, 9247], [0.41, 8839], [0.51, 8450], [0.61, 8071], [0.72, 7663], [0.82, 7265], [0.92, 6879], [1.02, 6469], [1.13, 6070], [1.23, 5671]]`

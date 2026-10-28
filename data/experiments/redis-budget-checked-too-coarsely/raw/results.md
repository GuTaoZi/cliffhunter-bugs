# redis budget-checked-too-coarsely: parent df45fed050d6 vs fix 485425cec76e

Two lists of 2,500,000 100-byte items filled alternately at list-max-ziplist-size 5, one deleted, then active defrag on (hz 100, cycle 25%: a 2,500 us budget per cycle) while a 1 ms PING probe runs on its own core (raw: round trip; cor: from the scheduled send time). defrag_cycle_*: the server's LATENCY HISTORY active-defrag-cycle. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 0.044 sd 0 [0.044, 0.044] (n=5) | 0.0442 sd 0.0004 [0.044, 0.045] (n=5) | 1.00 |
| raw_p99_ms | 0.1424 sd 0.12 [0.081, 0.385] (n=5) | 2.626 sd 0.01 [2.617, 2.639] (n=5) | 0.05 |
| raw_p999_ms | 0.616 sd 0.34 [0.116, 1.1] (n=5) | 2.715 sd 0.048 [2.666, 2.808] (n=5) | 0.23 |
| raw_max_ms | 177.8 sd 3.2 [175.6, 184.1] (n=5) | 4.47 sd 1.1 [3.548, 6.053] (n=5) | 39.78 |
| cor_p99_ms | 124.8 sd 2.9 [122.8, 130.5] (n=5) | 2.681 sd 0.025 [2.634, 2.702] (n=5) | 46.56 |
| cor_p999_ms | 173.1 sd 3.2 [170.9, 179.4] (n=5) | 3.338 sd 1.1 [2.71, 5.594] (n=5) | 51.86 |
| cor_max_ms | 177.9 sd 3.2 [175.7, 184.2] (n=5) | 4.522 sd 1.1 [3.561, 6.116] (n=5) | 39.34 |
| raw_over_10ms | 1 sd 0 [1, 1] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| raw_over_100ms | 1 sd 0 [1, 1] (n=5) | 0 sd 0 [0, 0] (n=5) | inf |
| blocked_ms | 177.4 sd 3.1 [174.6, 183.1] (n=5) | 280.7 sd 16 [258.2, 305.1] (n=5) | 0.63 |
| defrag_cycle_events | 1.2 sd 0.4 [1, 2] (n=5) | 3 sd 0 [3, 3] (n=5) | 0.40 |
| defrag_cycle_max_ms | 177.4 sd 3.4 [175, 184] (n=5) | 3 sd 0 [3, 3] (n=5) | 59.13 |
| defrag_s | 0.57 sd 0.017 [0.55, 0.6] (n=5) | 2.476 sd 0.078 [2.41, 2.61] (n=5) | 0.23 |
| defrag_hits | 6.164e+05 sd 0 [6.164e+05, 6.164e+05] (n=5) | 6.213e+05 sd 1.6e+02 [6.21e+05, 6.215e+05] (n=5) | 0.99 |
| frag_before | 2 sd 0 [2, 2] (n=5) | 2 sd 0 [2, 2] (n=5) | 1.00 |
| frag_after | 1 sd 0 [1, 1] (n=5) | 1 sd 0 [1, 1] (n=5) | 1.00 |
| server_cpu_s | 0.282 sd 0.004 [0.28, 0.29] (n=5) | 0.596 sd 0.033 [0.55, 0.65] (n=5) | 0.47 |
| main_thread_cpu_s | 0.276 sd 0.0049 [0.27, 0.28] (n=5) | 0.566 sd 0.027 [0.53, 0.61] (n=5) | 0.49 |
| server_peak_rss_mb | 654.9 sd 0.049 [654.8, 654.9] (n=5) | 654.8 sd 0.049 [654.8, 654.9] (n=5) | 1.00 |
| rss_mb_before | 654.6 sd 0.14 [654.3, 654.7] (n=5) | 654.5 sd 0.098 [654.4, 654.6] (n=5) | 1.00 |
| rss_mb_after | 654.1 sd 0.91 [652.3, 654.7] (n=5) | 639.7 sd 4 [635, 646.8] (n=5) | 1.02 |

parent, rep 1: `Value at:0x7791e0685be0 refcount:1 encoding:quicklist serializedlength:18000005 lru:14820318 lru_seconds_idle:0 ql_nodes:500000 ql_avg_node:5.00 ql_ziplist_max:5 ql_compressed:0 ql_uncompressed_size:2`; longest defrag cycles (ms) `[175]`

fix, rep 1: `Value at:0x77cc7d485be0 refcount:1 encoding:quicklist serializedlength:18000005 lru:14820327 lru_seconds_idle:0 ql_nodes:500000 ql_avg_node:5.00 ql_ziplist_max:5 ql_compressed:0 ql_uncompressed_size:2`; longest defrag cycles (ms) `[3, 2, 2]`

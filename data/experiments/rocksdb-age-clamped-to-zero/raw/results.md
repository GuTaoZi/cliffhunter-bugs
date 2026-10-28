# rocksdb age-clamped-to-zero: parent 80a59a03a7d6 vs fix 2f93a3b80912

db_bench fillseq, flush, readrandom, overwrite, stats: 64 column families sharing a 1 GB block cache, 1,200,000 keys, 256-byte blocks, stats dumped every second, on tmpfs. overwrite_*: per-write latency while the dumps run; collections_max: the LOG's count of block-cache scans; sec_*: per-second throughput over the whole run. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| overwrite_ops_per_s | 1.282e+05 sd 5.2e+03 [1.203e+05, 1.353e+05] (n=5) | 7.371e+05 sd 1.6e+04 [7.225e+05, 7.669e+05] (n=5) | 0.17 |
| overwrite_p50_us | 0.758 sd 0.022 [0.74, 0.8] (n=5) | 0.75 sd 0.021 [0.71, 0.77] (n=5) | 1.01 |
| overwrite_p99_us | 2.896 sd 0.029 [2.87, 2.95] (n=5) | 2.826 sd 0.051 [2.73, 2.87] (n=5) | 1.02 |
| overwrite_p999_us | 5.424 sd 0.093 [5.3, 5.58] (n=5) | 5.206 sd 0.11 [5.07, 5.33] (n=5) | 1.04 |
| overwrite_p9999_us | 9.556 sd 0.22 [9.18, 9.77] (n=5) | 9.12 sd 0.49 [8.18, 9.58] (n=5) | 1.05 |
| overwrite_max_us | 6.442e+06 sd 1.7e+05 [6.261e+06, 6.714e+06] (n=5) | 1.021e+04 sd 3.2e+03 [3748, 1.197e+04] (n=5) | 631.14 |
| overwrite_avg_us | 7.814 sd 0.32 [7.391, 8.31] (n=5) | 1.357 sd 0.028 [1.304, 1.384] (n=5) | 5.76 |
| readrandom_ops_per_s | 5.397e+05 sd 8.1e+03 [5.263e+05, 5.506e+05] (n=5) | 5.749e+05 sd 8.3e+03 [5.693e+05, 5.914e+05] (n=5) | 0.94 |
| readrandom_p99_us | 3.84 sd 0.026 [3.8, 3.88] (n=5) | 3.726 sd 0.053 [3.65, 3.81] (n=5) | 1.03 |
| readrandom_max_us | 2225 sd 3.6e+03 [336, 9520] (n=5) | 4068 sd 5.7e+03 [316, 1.521e+04] (n=5) | 0.55 |
| fillseq_ops_per_s | 2.343e+06 sd 1.1e+04 [2.322e+06, 2.351e+06] (n=5) | 2.366e+06 sd 7.5e+03 [2.356e+06, 2.375e+06] (n=5) | 0.99 |
| sec_ops_p5 | 0 sd 0 [0, 0] (n=5) | 8.051e+05 sd 1.1e+04 [7.954e+05, 8.269e+05] (n=5) | 0.00 |
| sec_ops_p50 | 0 sd 0 [0, 0] (n=5) | 8.051e+05 sd 1.1e+04 [7.954e+05, 8.269e+05] (n=5) | 0.00 |
| sec_under_5pct | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| sec_under_5pct_longest | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stats_dumps | 4 sd 0 [4, 4] (n=5) | 8 sd 0 [8, 8] (n=5) | 0.50 |
| log_cache_stats_lines | 89 sd 0 [89, 89] (n=5) | 169 sd 0 [169, 169] (n=5) | 0.53 |
| collections_max | 532 sd 0 [532, 532] (n=5) | 1 sd 0 [1, 1] (n=5) | 532.00 |
| wall_s | 17.27 sd 0.36 [16.8, 17.88] (n=5) | 9.048 sd 0.076 [8.909, 9.115] (n=5) | 1.91 |
| cpu_s | 21.75 sd 0.32 [21.36, 22.33] (n=5) | 9.069 sd 0.072 [8.937, 9.132] (n=5) | 2.40 |
| peak_rss_mb | 468.5 sd 0.29 [468.1, 469] (n=5) | 468.9 sd 0.53 [468, 469.6] (n=5) | 1.00 |

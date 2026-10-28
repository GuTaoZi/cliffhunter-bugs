# rocksdb age-clamped-to-zero: parent 80a59a03a7d6 vs fix 2f93a3b80912

db_bench fillseq, readrandom, overwrite, stats: 64 column families sharing a 1 GB block cache, 1,200,000 keys, 256-byte blocks, stats dumped every second, on tmpfs. overwrite_*: per-write latency while the dumps run; collections_max: the LOG's count of block-cache scans; sec_*: per-second throughput over the whole run. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| overwrite_ops_per_s | 5.813e+05 sd 1.2e+04 [5.611e+05, 5.944e+05] (n=5) | 5.75e+05 sd 7.7e+03 [5.632e+05, 5.836e+05] (n=5) | 1.01 |
| overwrite_p50_us | 1.174 sd 0.041 [1.13, 1.24] (n=5) | 1.212 sd 0.024 [1.19, 1.25] (n=5) | 0.97 |
| overwrite_p99_us | 3.054 sd 0.11 [2.97, 3.25] (n=5) | 3.136 sd 0.14 [3, 3.3] (n=5) | 0.97 |
| overwrite_p999_us | 5.652 sd 0.12 [5.48, 5.76] (n=5) | 5.768 sd 0.11 [5.66, 5.96] (n=5) | 0.98 |
| overwrite_p9999_us | 9.656 sd 0.29 [9.26, 9.98] (n=5) | 9.892 sd 0.092 [9.76, 9.99] (n=5) | 0.98 |
| overwrite_max_us | 1.838e+04 sd 85 [1.826e+04, 1.85e+04] (n=5) | 7634 sd 4.1e+03 [5542, 1.575e+04] (n=5) | 2.41 |
| overwrite_avg_us | 1.721 sd 0.037 [1.683, 1.782] (n=5) | 1.74 sd 0.024 [1.714, 1.776] (n=5) | 0.99 |
| readrandom_ops_per_s | 8.698e+05 sd 1.8e+04 [8.386e+05, 8.953e+05] (n=5) | 8.664e+05 sd 1.3e+04 [8.531e+05, 8.88e+05] (n=5) | 1.00 |
| readrandom_p99_us | 1.978 sd 0.0075 [1.97, 1.99] (n=5) | 1.976 sd 0.0049 [1.97, 1.98] (n=5) | 1.00 |
| readrandom_max_us | 2690 sd 5.1e+03 [78, 1.285e+04] (n=5) | 294.4 sd 2.5e+02 [74, 603] (n=5) | 9.14 |
| fillseq_ops_per_s | 2.32e+06 sd 5.7e+04 [2.209e+06, 2.367e+06] (n=5) | 2.326e+06 sd 7.9e+04 [2.168e+06, 2.371e+06] (n=5) | 1.00 |
| sec_ops_p5 | 5.44e+05 sd 9.5e+03 [5.29e+05, 5.55e+05] (n=5) | 5.477e+05 sd 1.5e+03 [5.458e+05, 5.5e+05] (n=5) | 0.99 |
| sec_ops_p50 | 6.222e+05 sd 1.3e+04 [6.013e+05, 6.348e+05] (n=5) | 6.076e+05 sd 1.3e+04 [5.882e+05, 6.207e+05] (n=5) | 1.02 |
| sec_under_5pct | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| sec_under_5pct_longest | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stats_dumps | 6.2 sd 0.4 [6, 7] (n=5) | 7 sd 0 [7, 7] (n=5) | 0.89 |
| log_cache_stats_lines | 173.6 sd 11 [168, 196] (n=5) | 196 sd 0 [196, 196] (n=5) | 0.89 |
| collections_max | 821.6 sd 51 [796, 924] (n=5) | 1 sd 0 [1, 1] (n=5) | 821.60 |
| wall_s | 7.401 sd 0.13 [7.25, 7.612] (n=5) | 7.507 sd 0.11 [7.42, 7.711] (n=5) | 0.99 |
| cpu_s | 7.391 sd 0.13 [7.242, 7.615] (n=5) | 7.406 sd 0.066 [7.3, 7.473] (n=5) | 1.00 |
| peak_rss_mb | 353.3 sd 0.32 [352.9, 353.8] (n=5) | 353.5 sd 0.31 [352.9, 353.8] (n=5) | 1.00 |

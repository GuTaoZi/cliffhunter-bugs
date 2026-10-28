# rocksdb waiting-on-nothing: parent e66221add4e8 vs fix d52f334cbd4b

db_bench fillseq of 800 1,000,000-byte values, 10 MB memtables (at most 4), one flush thread, auto compaction off, delayed_write_rate 1 MB/s, on tmpfs; fillseq_*: db_bench's per-write latency histogram; cum_stall: its stats benchmark; log_stalling_imm: the LOG's slowdowns on 3 waiting memtables. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| wall_s | 24.44 sd 2.3 [21.58, 26.36] (n=5) | 0.9912 sd 0.01 [0.982, 1.011] (n=5) | 24.65 |
| fillseq_ops_per_s | 32.8 sd 3.4 [30, 37] (n=5) | 839.4 sd 9.3 [821, 845] (n=5) | 0.04 |
| fillseq_p50_us | 360.4 sd 26 [332, 392.8] (n=5) | 354.5 sd 12 [343.4, 375.9] (n=5) | 1.02 |
| fillseq_p99_us | 1.001e+06 sd 8.8 [1.001e+06, 1.001e+06] (n=5) | 2.276e+04 sd 3.7e+02 [2.236e+04, 2.342e+04] (n=5) | 43.96 |
| fillseq_p999_us | 1.001e+06 sd 8.8 [1.001e+06, 1.001e+06] (n=5) | 2.325e+04 sd 7.7e+02 [2.236e+04, 2.447e+04] (n=5) | 43.04 |
| fillseq_max_us | 1.001e+06 sd 8.8 [1.001e+06, 1.001e+06] (n=5) | 2.325e+04 sd 7.7e+02 [2.236e+04, 2.447e+04] (n=5) | 43.04 |
| fillseq_avg_us | 3.048e+04 sd 2.9e+03 [2.692e+04, 3.286e+04] (n=5) | 1190 sd 13 [1183, 1216] (n=5) | 25.60 |
| cum_stall_s | 24 sd 2.4 [21, 26] (n=5) | 0.6624 sd 0.013 [0.647, 0.685] (n=5) | 36.24 |
| cum_stall_pct | 98.38 sd 0.72 [97.5, 99] (n=5) | 69.46 sd 0.68 [68.3, 70.3] (n=5) | 1.42 |
| stall_micros | 2.4e+07 sd 2.4e+06 [2.1e+07, 2.6e+07] (n=5) | 6.623e+05 sd 1.3e+04 [6.468e+05, 6.847e+05] (n=5) | 36.24 |
| sec_under_5pct | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stalling_imm | 24.2 sd 2.2 [21, 26] (n=5) | 52 sd 0 [52, 52] (n=5) | 0.47 |
| log_stopping_imm | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| log_stalling_l0 | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |  |
| cpu_s | 1.822 sd 0.04 [1.786, 1.887] (n=5) | 1.273 sd 0.01 [1.261, 1.291] (n=5) | 1.43 |
| peak_rss_mb | 47.58 sd 0.62 [46.7, 48.3] (n=5) | 48.56 sd 0.48 [47.6, 48.9] (n=5) | 0.98 |

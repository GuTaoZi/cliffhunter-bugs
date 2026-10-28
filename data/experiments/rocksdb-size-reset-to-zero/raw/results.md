# rocksdb size-reset-to-zero: parent 924616526a14 vs fix 04b2c16f9b81

seekrandom, use_direct_reads=true, seek_nexts=100,000, 2,000,000 keys (32 B + 512 B), 30 s per run; mean, sd [min, max] over repetitions.

| metric | parent | fix | fix / parent |
|---|---|---|---|
| mb_per_s | 188.5 sd 11 [166.4, 197.4] (n=5) | 250.8 sd 9.7 [242.7, 269.1] (n=5) | 1.33 |
| micros_per_op | 2.721e+05 sd 1.7e+04 [2.591e+05, 3.065e+05] (n=5) | 2.04e+05 sd 7.9e+03 [1.892e+05, 2.107e+05] (n=5) | 0.75 |
| ops_per_s | 3 sd 0 [3, 3] (n=5) | 4.2 sd 0.4 [4, 5] (n=5) | 1.40 |
| wall_s | 30.32 sd 0.18 [30.09, 30.51] (n=5) | 30.15 sd 0.048 [30.06, 30.19] (n=5) | 0.99 |
| user_s | 11.24 sd 0.41 [10.55, 11.66] (n=5) | 20.88 sd 0.76 [19.38, 21.45] (n=5) | 1.86 |
| sys_s | 1.028 sd 0.081 [0.89, 1.11] (n=5) | 0.314 sd 0.015 [0.29, 0.33] (n=5) | 0.31 |
| peak_rss_mb | 27.76 sd 0.39 [27.42, 28.52] (n=5) | 27.45 sd 0.16 [27.27, 27.64] (n=5) | 0.99 |

# SERVER-44991 (WiredTiger WT-5319): parent 33204938da7b vs fix 99636a29c679

Keys of 32 zero-padded digits, prefix_compression=true, 32 KB leaf pages; reopened after a checkpoint, so every key on a page read back is a cell. ckpt: 5 rounds of one update per 64 keys, then a timed checkpoint (ckpt_ms_warm: mean of rounds 2-5); evict: 8 threads updating random keys for 30 s in a 64 MB cache (per-update latency; app_evict_us: WiredTiger's application thread time evicting). cpu_s, peak_rss_mb: the process (runcmd.py). mean, sd [min, max]. Cells: disk, a fresh home per repetition on disk (each checkpoint writes and syncs about 270 MB); mem, homes on tmpfs with 16-byte values (key building dominates), one load per arm reused.

## Cell disk: 2,000,000 keys, 100-byte values

| metric | parent | fix | parent / fix |
|---|---|---|---|
| ckpt_ms_warm | 1774 sd 3.9e+02 [1283, 2217] (n=5) | 2155 sd 1.7e+02 [1862, 2371] (n=5) | 0.82 |
| ckpt_ms_mean | 1787 sd 3.8e+02 [1325, 2195] (n=5) | 2148 sd 1.7e+02 [1876, 2389] (n=5) | 0.83 |
| ckpt_ms_max | 1891 sd 3.6e+02 [1446, 2294] (n=5) | 2286 sd 2.1e+02 [1932, 2492] (n=5) | 0.83 |
| ckpt_rec_pages | 3.792e+04 sd 0 [3.792e+04, 3.792e+04] (n=5) | 3.792e+04 sd 0 [3.792e+04, 3.792e+04] (n=5) | 1.00 |
| ckpt_wall_s | 10.53 sd 1.9 [8.095, 12.74] (n=5) | 12.36 sd 0.76 [11.12, 13.48] (n=5) | 0.85 |
| ckpt_cpu_s | 6.583 sd 0.52 [5.683, 7.259] (n=5) | 4.806 sd 0.5 [4.086, 5.5] (n=5) | 1.37 |
| ckpt_peak_rss_mb | 316.4 sd 5.3 [309.9, 324.2] (n=5) | 323.8 sd 13 [308.5, 348.4] (n=5) | 0.98 |
| evict_per_s | 4.932e+04 sd 6e+03 [4.016e+04, 5.564e+04] (n=5) | 4.862e+04 sd 1.5e+03 [4.609e+04, 5.042e+04] (n=5) | 1.01 |
| evict_p50_us | 32.06 sd 4.6 [27.5, 40.7] (n=5) | 31.96 sd 8.1 [25.7, 46.8] (n=5) | 1.00 |
| evict_p99_us | 753.7 sd 56 [676.1, 831.8] (n=5) | 605.9 sd 27 [562.3, 631] (n=5) | 1.24 |
| evict_p999_us | 1402 sd 2.1e+02 [1148, 1698] (n=5) | 1031 sd 72 [891.3, 1096] (n=5) | 1.36 |
| evict_max_us | 7.008e+05 sd 7e+05 [1.018e+05, 1.963e+06] (n=5) | 1.862e+06 sd 6.6e+05 [5.956e+05, 2.414e+06] (n=5) | 0.38 |
| evict_app_evict_us | 1.677e+08 sd 6.4e+06 [1.604e+08, 1.777e+08] (n=5) | 1.881e+08 sd 1.8e+07 [1.65e+08, 2.069e+08] (n=5) | 0.89 |
| evict_rec_pages_eviction | 1.409e+06 sd 1.7e+05 [1.148e+06, 1.59e+06] (n=5) | 1.401e+06 sd 2.8e+04 [1.358e+06, 1.439e+06] (n=5) | 1.01 |
| evict_cpu_s | 369.9 sd 37 [311.3, 407] (n=5) | 326.5 sd 22 [292.9, 353.4] (n=5) | 1.13 |
| evict_peak_rss_mb | 38.44 sd 1.2 [36.8, 40.2] (n=5) | 32.78 sd 1.2 [31.4, 34.9] (n=5) | 1.17 |
| load_wall_s | 1.769 sd 0.34 [1.368, 2.179] (n=5) | 2.158 sd 0.051 [2.067, 2.21] (n=5) | 0.82 |
| load_cpu_s | 0.457 sd 0.0051 [0.452, 0.466] (n=5) | 0.457 sd 0.0044 [0.45, 0.463] (n=5) | 1.00 |

## Cell mem: 2,000,000 keys, 16-byte values

| metric | parent | fix | parent / fix |
|---|---|---|---|
| ckpt_ms_warm | 653.2 sd 13 [627, 661.8] (n=5) | 375.2 sd 25 [328.5, 399.9] (n=5) | 1.74 |
| ckpt_ms_mean | 650.4 sd 21 [607.6, 663.5] (n=5) | 361.3 sd 23 [318.6, 377.4] (n=5) | 1.80 |
| ckpt_ms_max | 662 sd 16 [631.6, 677.9] (n=5) | 393.1 sd 10 [380.3, 402.7] (n=5) | 1.68 |
| ckpt_rec_pages | 7849 sd 0 [7849, 7849] (n=5) | 7849 sd 0 [7849, 7849] (n=5) | 1.00 |
| ckpt_wall_s | 3.686 sd 0.1 [3.486, 3.751] (n=5) | 2.242 sd 0.12 [2.021, 2.332] (n=5) | 1.64 |
| ckpt_cpu_s | 3.034 sd 0.072 [2.895, 3.1] (n=5) | 1.741 sd 0.11 [1.556, 1.879] (n=5) | 1.74 |
| ckpt_peak_rss_mb | 146.9 sd 2.3 [142.4, 148.7] (n=5) | 145.1 sd 2.3 [140.9, 147.2] (n=5) | 1.01 |
| evict_per_s | 9526 sd 33 [9491, 9586] (n=5) | 1.577e+04 sd 4.2e+02 [1.534e+04, 1.64e+04] (n=5) | 0.60 |
| evict_p50_us | 32.54 sd 0.28 [32.4, 33.1] (n=5) | 35.34 sd 0.6 [34.7, 36.3] (n=5) | 0.92 |
| evict_p99_us | 4286 sd 74 [4169, 4365] (n=5) | 2582 sd 6.7e+02 [1862, 3715] (n=5) | 1.66 |
| evict_p999_us | 6398 sd 1.2e+02 [6310, 6607] (n=5) | 6376 sd 7e+02 [5495, 7586] (n=5) | 1.00 |
| evict_max_us | 1.291e+04 sd 2.7e+03 [1.109e+04, 1.82e+04] (n=5) | 1.732e+04 sd 3.6e+03 [1.386e+04, 2.29e+04] (n=5) | 0.75 |
| evict_app_evict_us | 2.23e+08 sd 2.1e+06 [2.205e+08, 2.264e+08] (n=5) | 2.213e+08 sd 1.6e+06 [2.19e+08, 2.228e+08] (n=5) | 1.01 |
| evict_rec_pages_eviction | 2.425e+05 sd 7.4e+02 [2.42e+05, 2.44e+05] (n=5) | 3.997e+05 sd 1.1e+04 [3.887e+05, 4.16e+05] (n=5) | 0.61 |
| evict_cpu_s | 444.5 sd 0.33 [444.1, 445.1] (n=5) | 421.9 sd 43 [348.4, 462.6] (n=5) | 1.05 |
| evict_peak_rss_mb | 26.76 sd 1.2 [25.5, 29] (n=5) | 28.18 sd 1.3 [26.8, 30.6] (n=5) | 0.95 |
| load_wall_s | 0.379 sd 0 [0.379, 0.379] (n=1) | 0.372 sd 0 [0.372, 0.372] (n=1) | 1.02 |
| load_cpu_s | 0.379 sd 0 [0.379, 0.379] (n=1) | 0.372 sd 0 [0.372, 0.372] (n=1) | 1.02 |


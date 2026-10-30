# postgres gave-up-advising-early: parent 11bd8318602f vs fix 7ea8cd15661e

Cold VACUUM (VERBOSE) of a 400,000-block table whose non-skippable pages are runs of R blocks in every 400 (held by a prepared transaction, so the scan is read-only). io_read_ms: VACUUM's reported read time; device_mb_read: the disk's sectors read during the VACUUM; resident_pages_after: the table's 4 kB pages in the page cache after it. mean, sd [min, max].

## t48: runs of 48 blocks (the trigger)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| vacuum_wall_s | 15.2 sd 0.39 [14.88, 15.95] (n=5) | 10.53 sd 0.22 [10.16, 10.78] (n=5) | 1.44 |
| vacuum_elapsed_s | 15.19 sd 0.39 [14.87, 15.94] (n=5) | 10.52 sd 0.21 [10.15, 10.77] (n=5) | 1.44 |
| io_read_ms | 1.485e+04 sd 3.9e+02 [1.453e+04, 1.561e+04] (n=5) | 1.027e+04 sd 2.1e+02 [9891, 1.051e+04] (n=5) | 1.45 |
| read_mb_s | 24.76 sd 0.62 [23.57, 25.27] (n=5) | 35.73 sd 0.74 [34.88, 37.02] (n=5) | 0.69 |
| pages_scanned | 4.8e+04 sd 0 [4.8e+04, 4.8e+04] (n=5) | 4.8e+04 sd 0 [4.8e+04, 4.8e+04] (n=5) | 1.00 |
| device_mb_read | 875.2 sd 0.2 [874.8, 875.3] (n=5) | 875.8 sd 0 [875.8, 875.8] (n=5) | 1.00 |
| resident_pages_after | 2.242e+05 sd 0 [2.242e+05, 2.242e+05] (n=5) | 2.242e+05 sd 0 [2.242e+05, 2.242e+05] (n=5) | 1.00 |
| server_cpu_s | 0.668 sd 0.004 [0.66, 0.67] (n=5) | 0.622 sd 0.046 [0.53, 0.65] (n=5) | 1.07 |
| server_peak_rss_mb | 37.12 sd 0.36 [36.4, 37.3] (n=5) | 37.14 sd 0.049 [37.1, 37.2] (n=5) | 1.00 |

## t16: runs of 16 blocks (control: one chunk per run)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| vacuum_wall_s | 3.876 sd 0.044 [3.841, 3.938] (n=3) | 5.838 sd 0.19 [5.571, 5.999] (n=3) | 0.66 |
| vacuum_elapsed_s | 3.867 sd 0.045 [3.83, 3.93] (n=3) | 5.827 sd 0.19 [5.56, 5.99] (n=3) | 0.66 |
| io_read_ms | 3723 sd 41 [3689, 3781] (n=3) | 5742 sd 1.9e+02 [5477, 5901] (n=3) | 0.65 |
| read_mb_s | 32.53 sd 0.36 [32.01, 32.81] (n=3) | 21.61 sd 0.72 [21, 22.62] (n=3) | 1.51 |
| pages_scanned | 1.6e+04 sd 0 [1.6e+04, 1.6e+04] (n=3) | 1.6e+04 sd 0 [1.6e+04, 1.6e+04] (n=3) | 1.00 |
| device_mb_read | 126.1 sd 0 [126.1, 126.1] (n=3) | 126.1 sd 0 [126.1, 126.1] (n=3) | 1.00 |
| resident_pages_after | 3.229e+04 sd 0 [3.229e+04, 3.229e+04] (n=3) | 3.229e+04 sd 0 [3.229e+04, 3.229e+04] (n=3) | 1.00 |
| server_cpu_s | 0.1767 sd 0.0047 [0.17, 0.18] (n=3) | 0.1767 sd 0.0047 [0.17, 0.18] (n=3) | 1.00 |
| server_peak_rss_mb | 37.33 sd 0.094 [37.2, 37.4] (n=3) | 37.17 sd 0.047 [37.1, 37.2] (n=3) | 1.00 |

## t48 with maintenance_io_concurrency 0 (control: no advice)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| vacuum_wall_s | 10.38 sd 0.038 [10.33, 10.42] (n=3) | 10.41 sd 0.18 [10.18, 10.61] (n=3) | 1.00 |
| vacuum_elapsed_s | 10.37 sd 0.039 [10.32, 10.41] (n=3) | 10.4 sd 0.18 [10.17, 10.6] (n=3) | 1.00 |
| io_read_ms | 1.011e+04 sd 39 [1.006e+04, 1.015e+04] (n=3) | 1.014e+04 sd 1.8e+02 [9910, 1.034e+04] (n=3) | 1.00 |
| read_mb_s | 36.22 sd 0.13 [36.1, 36.41] (n=3) | 36.15 sd 0.61 [35.45, 36.94] (n=3) | 1.00 |
| pages_scanned | 4.8e+04 sd 0 [4.8e+04, 4.8e+04] (n=3) | 4.8e+04 sd 0 [4.8e+04, 4.8e+04] (n=3) | 1.00 |
| device_mb_read | 875.8 sd 0 [875.8, 875.8] (n=3) | 875.8 sd 0 [875.8, 875.8] (n=3) | 1.00 |
| resident_pages_after | 2.242e+05 sd 0 [2.242e+05, 2.242e+05] (n=3) | 2.242e+05 sd 0 [2.242e+05, 2.242e+05] (n=3) | 1.00 |
| server_cpu_s | 0.65 sd 0 [0.65, 0.65] (n=3) | 0.6467 sd 0.0047 [0.64, 0.65] (n=3) | 1.01 |
| server_peak_rss_mb | 37.3 sd 0 [37.3, 37.3] (n=3) | 37.17 sd 0.094 [37.1, 37.3] (n=3) | 1.00 |


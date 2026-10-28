# postgres decay-outruns-growth: parent cceb1bf45e3a vs fix 6e36930f9aaf

One sequential scan of a 320,000-block table (one row per block) on disk, io_method worker with 16 io workers, shared_buffers 16GB. warm: 63 blocks in every 64 in shared buffers and the 64th dropped from the OS cache, so each device read follows 63 hits; allcold (control): every block a device read. This disk's queue-depth-1 8 kB random read: 3.9737 ms median. read_per_cold_block_ms: scan wall time per device-read block. mean, sd [min, max].

## warm, effective_io_concurrency 16

| metric | parent | fix | parent / fix |
|---|---|---|---|
| scan_wall_s | 22.99 sd 1.2 [22.01, 24.65] (n=3) | 11.2 sd 0.1 [11.06, 11.27] (n=3) | 2.05 |
| scan_exec_ms | 2.298e+04 sd 1.2e+03 [2.2e+04, 2.464e+04] (n=3) | 1.12e+04 sd 1e+02 [1.105e+04, 1.127e+04] (n=3) | 2.05 |
| read_per_cold_block_ms | 4.597 sd 0.24 [4.401, 4.929] (n=3) | 2.24 sd 0.02 [2.212, 2.255] (n=3) | 2.05 |
| scan_hit | 3.15e+05 sd 0 [3.15e+05, 3.15e+05] (n=3) | 3.15e+05 sd 0 [3.15e+05, 3.15e+05] (n=3) | 1.00 |
| scan_read | 5000 sd 0 [5000, 5000] (n=3) | 5000 sd 0 [5000, 5000] (n=3) | 1.00 |
| resident_pages_before_scan | 0 sd 0 [0, 0] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| server_cpu_s | 14.98 sd 0.049 [14.92, 15.04] (n=3) | 7.957 sd 0.2 [7.68, 8.15] (n=3) | 1.88 |
| server_peak_rss_mb | 2576 sd 0.71 [2575, 2577] (n=3) | 2574 sd 1.2 [2573, 2576] (n=3) | 1.00 |

## warm, effective_io_concurrency 64

| metric | parent | fix | parent / fix |
|---|---|---|---|
| scan_wall_s | 24.31 sd 2.2 [22.19, 27.41] (n=3) | 9.895 sd 2 [8.314, 12.68] (n=3) | 2.46 |
| scan_exec_ms | 2.43e+04 sd 2.2e+03 [2.218e+04, 2.74e+04] (n=3) | 9890 sd 2e+03 [8309, 1.268e+04] (n=3) | 2.46 |
| read_per_cold_block_ms | 4.862 sd 0.45 [4.438, 5.481] (n=3) | 1.979 sd 0.4 [1.663, 2.537] (n=3) | 2.46 |
| scan_hit | 3.15e+05 sd 0 [3.15e+05, 3.15e+05] (n=3) | 3.15e+05 sd 0 [3.15e+05, 3.15e+05] (n=3) | 1.00 |
| scan_read | 5000 sd 0 [5000, 5000] (n=3) | 5000 sd 0 [5000, 5000] (n=3) | 1.00 |
| resident_pages_before_scan | 0 sd 0 [0, 0] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| server_cpu_s | 14.62 sd 0.39 [14.08, 14.93] (n=3) | 5.797 sd 0.18 [5.6, 6.03] (n=3) | 2.52 |
| server_peak_rss_mb | 2577 sd 0.71 [2576, 2578] (n=3) | 2573 sd 1.5 [2571, 2575] (n=3) | 1.00 |

## allcold, effective_io_concurrency 64

| metric | parent | fix | parent / fix |
|---|---|---|---|
| scan_wall_s | 21.28 sd 0 [21.28, 21.28] (n=1) | 24.88 sd 0 [24.88, 24.88] (n=1) | 0.86 |
| scan_exec_ms | 2.127e+04 sd 0 [2.127e+04, 2.127e+04] (n=1) | 2.487e+04 sd 0 [2.487e+04, 2.487e+04] (n=1) | 0.86 |
| read_per_cold_block_ms | 0.0665 sd 0 [0.0665, 0.0665] (n=1) | 0.0778 sd 0 [0.0778, 0.0778] (n=1) | 0.85 |
| scan_hit | 0 sd 0 [0, 0] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| scan_read | 3.2e+05 sd 0 [3.2e+05, 3.2e+05] (n=1) | 3.2e+05 sd 0 [3.2e+05, 3.2e+05] (n=1) | 1.00 |
| resident_pages_before_scan | 0 sd 0 [0, 0] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| server_cpu_s | 22.16 sd 0 [22.16, 22.16] (n=1) | 23.25 sd 0 [23.25, 23.25] (n=1) | 0.95 |
| server_peak_rss_mb | 2576 sd 0 [2576, 2576] (n=1) | 2577 sd 0 [2577, 2577] (n=1) | 1.00 |

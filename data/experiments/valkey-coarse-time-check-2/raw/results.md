# valkey coarse-time-check-2: parent cef8822f60b6 vs fix 3213f48fd694

Hashes whose fields all expire at the same instant T, a PING every 1 ms from T-5 s until the database is empty. raw_*/cor_*: the PINGs in [T, drained] (cor_: from the time each PING was due); base_*: [T-5, T) in the same run. d_*: INFO stats deltas over the drain. control: one hash of 5,000,000 fields. mean, sd [min, max].

## 10,000 hashes of 1,000 fields (the trigger)

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 0.04075 sd 0.00043 [0.04, 0.041] (n=4) | 0.05225 sd 0.00043 [0.052, 0.053] (n=4) | 0.78 |
| raw_p99_ms | 26.59 sd 7.3 [15.8, 33.98] (n=4) | 2.861 sd 0.07 [2.809, 2.982] (n=4) | 9.29 |
| raw_max_ms | 46.28 sd 1.3 [45.2, 48.52] (n=4) | 30.39 sd 2 [28.8, 33.85] (n=4) | 1.52 |
| cor_p50_ms | 426.1 sd 2e+02 [234.7, 761.7] (n=4) | 1.413 sd 0.064 [1.325, 1.506] (n=4) | 301.57 |
| cor_p99_ms | 976.1 sd 1.8e+02 [797.7, 1275] (n=4) | 35.15 sd 9.5 [27.5, 51.08] (n=4) | 27.77 |
| blocked_ms | 1315 sd 27 [1283, 1352] (n=4) | 1841 sd 1e+02 [1753, 2018] (n=4) | 0.71 |
| base_raw_p50_ms | 0.049 sd 0.0031 [0.044, 0.052] (n=4) | 0.05075 sd 0.00043 [0.05, 0.051] (n=4) | 0.97 |
| base_raw_p99_ms | 0.1618 sd 0.012 [0.142, 0.172] (n=4) | 0.176 sd 0.039 [0.121, 0.23] (n=4) | 0.92 |
| expire_cycle_max_ms | 32 sd 1.6 [30, 34] (n=4) | 25.5 sd 0.5 [25, 26] (n=4) | 1.25 |
| d_expired_fields | 1e+07 sd 0 [1e+07, 1e+07] (n=4) | 1e+07 sd 0 [1e+07, 1e+07] (n=4) | 1.00 |
| d_expired_time_cap_reached_count | 286.8 sd 1.1 [285, 288] (n=4) | 2387 sd 84 [2304, 2520] (n=4) | 0.12 |
| d_expire_cycle_cpu_milliseconds | 1551 sd 29 [1517, 1592] (n=4) | 5047 sd 1.8e+02 [4882, 5331] (n=4) | 0.31 |
| drain_s | 1.683 sd 0.068 [1.61, 1.76] (n=4) | 7.402 sd 0.23 [7.09, 7.73] (n=4) | 0.23 |
| server_cpu_s | 1.887 sd 0.039 [1.85, 1.94] (n=4) | 5.603 sd 0.23 [5.46, 6] (n=4) | 0.34 |
| server_peak_rss_mb | 1051 sd 0.65 [1050, 1052] (n=4) | 1051 sd 1.7 [1049, 1053] (n=4) | 1.00 |

## Control: one hash of 5M fields

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 43.34 sd 0 [43.34, 43.34] (n=1) | 1.8 sd 0 [1.8, 1.8] (n=1) | 24.08 |
| raw_p99_ms | 240.1 sd 0 [240.1, 240.1] (n=1) | 32.54 sd 0 [32.54, 32.54] (n=1) | 7.38 |
| raw_max_ms | 248.4 sd 0 [248.4, 248.4] (n=1) | 39.19 sd 0 [39.19, 39.19] (n=1) | 6.34 |
| cor_p50_ms | 7178 sd 0 [7178, 7178] (n=1) | 16.4 sd 0 [16.4, 16.4] (n=1) | 437.71 |
| cor_p99_ms | 5.795e+04 sd 0 [5.795e+04, 5.795e+04] (n=1) | 3.344e+04 sd 0 [3.344e+04, 3.344e+04] (n=1) | 1.73 |
| blocked_ms | 5.965e+04 sd 0 [5.965e+04, 5.965e+04] (n=1) | 3.809e+04 sd 0 [3.809e+04, 3.809e+04] (n=1) | 1.57 |
| base_raw_p50_ms | 0.052 sd 0 [0.052, 0.052] (n=1) | 0.051 sd 0 [0.051, 0.051] (n=1) | 1.02 |
| base_raw_p99_ms | 0.219 sd 0 [0.219, 0.219] (n=1) | 0.134 sd 0 [0.134, 0.134] (n=1) | 1.63 |
| expire_cycle_max_ms | 83 sd 0 [83, 83] (n=1) | 29 sd 0 [29, 29] (n=1) | 2.86 |
| d_expired_fields | 1.856e+06 sd 0 [1.856e+06, 1.856e+06] (n=1) | 1.786e+06 sd 0 [1.786e+06, 1.786e+06] (n=1) | 1.04 |
| d_expired_time_cap_reached_count | 1381 sd 0 [1381, 1381] (n=1) | 1.595e+04 sd 0 [1.595e+04, 1.595e+04] (n=1) | 0.09 |
| d_expire_cycle_cpu_milliseconds | 6.002e+04 sd 0 [6.002e+04, 6.002e+04] (n=1) | 5.584e+04 sd 0 [5.584e+04, 5.584e+04] (n=1) | 1.07 |
| drain_s | 60.42 sd 0 [60.42, 60.42] (n=1) | 60.13 sd 0 [60.13, 60.13] (n=1) | 1.00 |
| server_cpu_s | 59.82 sd 0 [59.82, 59.82] (n=1) | 56.17 sd 0 [56.17, 56.17] (n=1) | 1.06 |
| server_peak_rss_mb | 433.7 sd 0 [433.7, 433.7] (n=1) | 433.7 sd 0 [433.7, 433.7] (n=1) | 1.00 |

## Check: 2,000 hashes

```
[
 {
  "arm": "parent",
  "rep": 0,
  "hashes": 2000,
  "load_margin_s": 36.2,
  "raw_p50_ms": 0.041,
  "raw_p99_ms": 19.738,
  "cor_p99_ms": 331.73,
  "raw_max_ms": 45.566,
  "blocked_ms": 399.2,
  "expire_cycle_max_ms": 30,
  "d_expired_fields": 2000000,
  "d_expired_time_cap_reached_count": 60,
  "drain_s": 0.56,
  "server_cpu_s": 0.65,
  "server_peak_rss_mb": 217.6,
  "d_expire_cycle_cpu_milliseconds": 446,
  "aborted": null
 },
 {
  "arm": "fix",
  "rep": 0,
  "hashes": 2000,
  "load_margin_s": 35.4,
  "raw_p50_ms": 0.052,
  "raw_p99_ms": 2.481,
  "cor_p99_ms": 26.971,
  "raw_max_ms": 27.957,
  "blocked_ms": 387.2,
  "expire_cycle_max_ms": 26,
  "d_expired_fields": 2000000,
  "d_expired_time_cap_reached_count": 483,
  "drain_s": 1.63,
  "server_cpu_s": 1.29,
  "server_peak_rss_mb": 217.6,
  "d_expire_cycle_cpu_milliseconds": 1058,
  "aborted": null
 }
]
```

# redis empty-sample-means-repeat: parent 02a87885e64c vs fix f20774eced7e

300,000 keys with a TTL, a BGSAVE child kept alive, all but 300 keys deleted, then 30 s of a PING every 1 ms (raw_*: round trip; cor_*: from the time each PING was due; blocked_ms: time beyond 1 ms the server did not answer). d_*: INFO stats deltas over the window. control: no BGSAVE. mean, sd [min, max].

## With a fork child (the trigger)

expires dict stuck mid-rehash: 8 of 8 runs

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 0.05125 sd 0.00043 [0.051, 0.052] (n=4) | 0.0485 sd 0.0032 [0.043, 0.051] (n=4) | 1.06 |
| raw_p99_ms | 1.066 sd 0.0036 [1.061, 1.071] (n=4) | 0.081 sd 0.015 [0.064, 0.099] (n=4) | 13.16 |
| raw_p999_ms | 26.13 sd 0.021 [26.11, 26.16] (n=4) | 0.1065 sd 0.0017 [0.104, 0.108] (n=4) | 245.33 |
| raw_max_ms | 26.2 sd 0.049 [26.14, 26.28] (n=4) | 0.5525 sd 0.35 [0.332, 1.152] (n=4) | 47.43 |
| cor_p50_ms | 1.113 sd 0.0005 [1.112, 1.113] (n=4) | 0.108 sd 0.0035 [0.102, 0.11] (n=4) | 10.30 |
| cor_p99_ms | 25.26 sd 0.014 [25.25, 25.29] (n=4) | 0.147 sd 0.0091 [0.137, 0.16] (n=4) | 171.86 |
| cor_p999_ms | 26.23 sd 0.0099 [26.22, 26.25] (n=4) | 0.1762 sd 0.0078 [0.165, 0.186] (n=4) | 148.81 |
| cor_max_ms | 26.3 sd 0.064 [26.25, 26.41] (n=4) | 4.259 sd 3.4 [0.464, 7.693] (n=4) | 6.18 |
| raw_over_10ms | 238.2 sd 0.43 [238, 239] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| blocked_ms | 5954 sd 10 [5944, 5969] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| d_expired_time_cap_reached_count | 1.036e+04 sd 59 [1.029e+04, 1.045e+04] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| d_expire_cycle_cpu_milliseconds | 1.61e+04 sd 50 [1.604e+04, 1.618e+04] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| main_thread_cpu_s | 16.55 sd 0.038 [16.5, 16.6] (n=4) | 0.53 sd 0.0071 [0.52, 0.54] (n=4) | 31.22 |
| server_cpu_s | 16.54 sd 0.048 [16.48, 16.6] (n=4) | 0.535 sd 0.0087 [0.53, 0.55] (n=4) | 30.91 |
| server_peak_rss_mb | 44.25 sd 0.61 [43.9, 45.3] (n=4) | 43.88 sd 0.083 [43.8, 44] (n=4) | 1.01 |

## Control: no fork child

expires dict stuck mid-rehash: 0 of 2 runs

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_p50_ms | 0.044 sd 0 [0.044, 0.044] (n=1) | 0.051 sd 0 [0.051, 0.051] (n=1) | 0.86 |
| raw_p99_ms | 0.125 sd 0 [0.125, 0.125] (n=1) | 0.161 sd 0 [0.161, 0.161] (n=1) | 0.78 |
| raw_p999_ms | 0.999 sd 0 [0.999, 0.999] (n=1) | 0.995 sd 0 [0.995, 0.995] (n=1) | 1.00 |
| raw_max_ms | 2.705 sd 0 [2.705, 2.705] (n=1) | 2.939 sd 0 [2.939, 2.939] (n=1) | 0.92 |
| cor_p50_ms | 0.105 sd 0 [0.105, 0.105] (n=1) | 0.111 sd 0 [0.111, 0.111] (n=1) | 0.95 |
| cor_p99_ms | 0.19 sd 0 [0.19, 0.19] (n=1) | 0.27 sd 0 [0.27, 0.27] (n=1) | 0.70 |
| cor_p999_ms | 2.716 sd 0 [2.716, 2.716] (n=1) | 2.975 sd 0 [2.975, 2.975] (n=1) | 0.91 |
| cor_max_ms | 2.795 sd 0 [2.795, 2.795] (n=1) | 7.715 sd 0 [7.715, 7.715] (n=1) | 0.36 |
| raw_over_10ms | 0 sd 0 [0, 0] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| blocked_ms | 5 sd 0 [5, 5] (n=1) | 22.4 sd 0 [22.4, 22.4] (n=1) | 0.22 |
| d_expired_time_cap_reached_count | 0 sd 0 [0, 0] (n=1) | 0 sd 0 [0, 0] (n=1) |  |
| d_expire_cycle_cpu_milliseconds | 2 sd 0 [2, 2] (n=1) | 3 sd 0 [3, 3] (n=1) | 0.67 |
| main_thread_cpu_s | 0.57 sd 0 [0.57, 0.57] (n=1) | 0.58 sd 0 [0.58, 0.58] (n=1) | 0.98 |
| server_cpu_s | 0.58 sd 0 [0.58, 0.58] (n=1) | 0.58 sd 0 [0.58, 0.58] (n=1) | 1.00 |
| server_peak_rss_mb | 31.8 sd 0 [31.8, 31.8] (n=1) | 36.3 sd 0 [36.3, 36.3] (n=1) | 0.88 |


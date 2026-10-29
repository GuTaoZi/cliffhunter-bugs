# memcached clock-underflow: parent e31a59121031 vs fix d7324b0bd108

A fresh server, 1,000,000 keys of 64 bytes, then 25 s of closed-loop multigets of 64 random keys per request from pinned client processes (p*_us: per-request latency); the phase ends before uptime 54 s. late: the same after 65 s of uptime. Server CPU and peak RSS over the phase. mean, sd [min, max].

## Cell A: -t 4, 8 clients

| metric | parent | fix | parent / fix |
|---|---|---|---|
| keys_per_s | 2.555e+06 sd 5.9e+04 [2.466e+06, 2.625e+06] (n=4) | 7.221e+06 sd 1.5e+04 [7.202e+06, 7.237e+06] (n=4) | 0.35 |
| p50_us | 202.1 sd 5.1 [196.3, 210.1] (n=4) | 69.6 sd 0.14 [69.46, 69.77] (n=4) | 2.90 |
| p99_us | 248.2 sd 5.3 [242.2, 255.9] (n=4) | 83.87 sd 0.31 [83.49, 84.32] (n=4) | 2.96 |
| p999_us | 260.8 sd 5.8 [253.9, 269.5] (n=4) | 213 sd 0.45 [212.5, 213.4] (n=4) | 1.22 |
| max_us | 1793 sd 7.3e+02 [1208, 3000] (n=4) | 1752 sd 8.9e+02 [1219, 3285] (n=4) | 1.02 |
| mean_us | 200 sd 4.6 [194.5, 207] (n=4) | 70.35 sd 0.15 [70.19, 70.53] (n=4) | 2.84 |
| server_cpu_s | 94.5 sd 0.11 [94.4, 94.69] (n=4) | 84.69 sd 0.076 [84.6, 84.77] (n=4) | 1.12 |
| server_peak_rss_mb | 155.9 sd 0 [155.9, 155.9] (n=4) | 155.9 sd 0.043 [155.9, 156] (n=4) | 1.00 |
| uptime_start | 3 sd 0 [3, 3] (n=4) | 3 sd 0 [3, 3] (n=4) | 1.00 |
| uptime_end | 28 sd 0 [28, 28] (n=4) | 29 sd 0 [29, 29] (n=4) | 0.97 |

## Cell A late: -t 4, 8 clients

| metric | parent | fix | parent / fix |
|---|---|---|---|
| keys_per_s | 7.237e+06 sd 9.2e+03 [7.228e+06, 7.246e+06] (n=2) | 7.228e+06 sd 4e+03 [7.224e+06, 7.232e+06] (n=2) | 1.00 |
| p50_us | 69.47 sd 0.09 [69.38, 69.56] (n=2) | 69.52 sd 0.044 [69.48, 69.57] (n=2) | 1.00 |
| p99_us | 83.58 sd 0.2 [83.38, 83.77] (n=2) | 84.85 sd 0.38 [84.47, 85.23] (n=2) | 0.98 |
| p999_us | 212.5 sd 0.23 [212.3, 212.8] (n=2) | 213.2 sd 0.17 [213, 213.3] (n=2) | 1.00 |
| max_us | 969 sd 1.5e+02 [816.5, 1122] (n=2) | 1050 sd 1.2e+02 [930.9, 1169] (n=2) | 0.92 |
| mean_us | 70.19 sd 0.09 [70.1, 70.28] (n=2) | 70.27 sd 0.041 [70.23, 70.31] (n=2) | 1.00 |
| server_cpu_s | 84.7 sd 0.05 [84.65, 84.75] (n=2) | 84.78 sd 0.03 [84.75, 84.81] (n=2) | 1.00 |
| server_peak_rss_mb | 155.9 sd 0 [155.9, 155.9] (n=2) | 155.9 sd 0 [155.9, 155.9] (n=2) | 1.00 |
| uptime_start | 68.5 sd 0.5 [68, 69] (n=2) | 68.5 sd 0.5 [68, 69] (n=2) | 1.00 |
| uptime_end | 94.5 sd 0.5 [94, 95] (n=2) | 95 sd 0 [95, 95] (n=2) | 0.99 |

## Cell B: -t 16, 16 clients

| metric | parent | fix | parent / fix |
|---|---|---|---|
| keys_per_s | 2.197e+06 sd 3.2e+05 [1.69e+06, 2.576e+06] (n=4) | 1.329e+07 sd 7.7e+04 [1.318e+07, 1.338e+07] (n=4) | 0.17 |
| p50_us | 245.1 sd 48 [212.3, 328.2] (n=4) | 77.9 sd 0.35 [77.46, 78.38] (n=4) | 3.15 |
| p99_us | 3613 sd 6.8e+02 [2795, 4632] (n=4) | 95.58 sd 0.17 [95.43, 95.85] (n=4) | 37.80 |
| p999_us | 1.913e+04 sd 5.7e+03 [1.115e+04, 2.641e+04] (n=4) | 111.2 sd 6.2 [104.6, 119.9] (n=4) | 172.06 |
| max_us | 3.274e+04 sd 1.1e+04 [1.939e+04, 4.844e+04] (n=4) | 2005 sd 7.8e+02 [1101, 3205] (n=4) | 16.33 |
| mean_us | 476.9 sd 78 [396.9, 605.4] (n=4) | 76.37 sd 0.44 [75.87, 77] (n=4) | 6.24 |
| server_cpu_s | 372.1 sd 4.1 [367.3, 378.6] (n=4) | 213.5 sd 1.5 [211.4, 215.3] (n=4) | 1.74 |
| server_peak_rss_mb | 156.4 sd 0 [156.4, 156.4] (n=4) | 156.4 sd 0 [156.4, 156.4] (n=4) | 1.00 |
| uptime_start | 3 sd 0 [3, 3] (n=4) | 3 sd 0 [3, 3] (n=4) | 1.00 |
| uptime_end | 28 sd 0 [28, 28] (n=4) | 30.25 sd 0.43 [30, 31] (n=4) | 0.93 |

## Decision check: the LRU head after getting 10,000 keys in descending order

```
[
 {
  "arm": "parent",
  "lru_head": "ITEM k0000000 [64 b; 1793293448 s]",
  "age": "0",
  "uptime": "7"
 },
 {
  "arm": "fix",
  "lru_head": "ITEM k0009999 [64 b; 1793293394 s]",
  "age": "5",
  "uptime": "7"
 }
]
```

# valkey forced-synchronous-catch-up: parent dcbaecddce5d vs fix aefed3d363d1

A set of 10,000,000 string members shrunk with SREM to exactly 1,908,408 (the 13% threshold of its 2^21-bucket table), then 2,300,000 new members added by closed-loop SADDs of 100, with a PING every 1 ms. sadd_*: per-command latency (max, the command index where it fell, median, total); raw_*/blocked_ms: the PINGs. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| sadd_max_ms | 63.37 sd 4.1 [56.25, 66.1] (n=4) | 18.91 sd 0.39 [18.32, 19.28] (n=4) | 3.35 |
| sadd_max_at_cmd | 1.762e+04 sd 0 [1.762e+04, 1.762e+04] (n=4) | 2.097e+04 sd 0 [2.097e+04, 2.097e+04] (n=4) | 0.84 |
| sadd_p50_ms | 0.2051 sd 0.041 [0.1336, 0.2293] (n=4) | 0.2036 sd 0.041 [0.1329, 0.2287] (n=4) | 1.01 |
| sadd_total_s | 5.402 sd 1.2 [3.4, 6.1] (n=4) | 5.055 sd 0.96 [3.42, 5.75] (n=4) | 1.07 |
| raw_max_ms | 62.78 sd 4.1 [55.72, 65.72] (n=4) | 18.39 sd 0.59 [17.8, 19.15] (n=4) | 3.41 |
| raw_p999_ms | 0.6482 sd 0.028 [0.612, 0.69] (n=4) | 0.8887 sd 0.097 [0.721, 0.958] (n=4) | 0.73 |
| blocked_ms | 64.03 sd 4.8 [55.7, 67.2] (n=4) | 17.38 sd 0.58 [16.8, 18.1] (n=4) | 3.68 |
| raw_over_100ms | 0 sd 0 [0, 0] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| server_cpu_s | 2.795 sd 0.29 [2.3, 2.96] (n=4) | 2.525 sd 0.16 [2.27, 2.67] (n=4) | 1.11 |
| server_peak_rss_mb | 253.5 sd 2.2 [249.9, 255.6] (n=4) | 264.7 sd 18 [254.1, 296.1] (n=4) | 0.96 |
| load_s | 27.23 sd 3 [22, 29.4] (n=4) | 26.3 sd 4.1 [19.4, 29.6] (n=4) | 1.04 |

## Check (2^18 buckets)

```
[
 {
  "arm": "parent",
  "sadd_max_ms": 10.71381289511919,
  "sadd_max_at_cmd": 2202,
  "sadd_top3_ms": [
   10.71,
   1.04,
   1.03
  ]
 },
 {
  "arm": "fix",
  "sadd_max_ms": 1.021787989884615,
  "sadd_max_at_cmd": 0,
  "sadd_top3_ms": [
   1.02,
   0.81,
   0.76
  ]
 }
]
```

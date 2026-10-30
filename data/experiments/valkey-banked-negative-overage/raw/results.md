# valkey banked-negative-overage: parent 1acf7f71c032 vs fix 0c8ad5cd3412

2,000,000 keys in db15 only, every other one unlinked; defrag effort pinned at 1%; 10 defrag restarts in 46 s, each passing 30 empty stages before db15, with a PING every 1 ms (raw_*: round trip; cor_*: from the time each PING was due; blocked_ms: time beyond 1 ms the server did not answer). defrag_cycle_max_ms: the largest active-defrag-cycle latency event. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| raw_max_ms | 13.45 sd 0.0087 [13.43, 13.46] (n=4) | 1.908 sd 0.95 [0.939, 2.932] (n=4) | 7.05 |
| raw_p999_ms | 0.5962 sd 0.0019 [0.594, 0.599] (n=4) | 0.5917 sd 0.0011 [0.59, 0.593] (n=4) | 1.01 |
| cor_p999_ms | 9.528 sd 0.26 [9.079, 9.681] (n=4) | 0.6415 sd 0.022 [0.604, 0.655] (n=4) | 14.85 |
| raw_over_10ms | 10 sd 0 [10, 10] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| blocked_ms | 121.7 sd 0.61 [121.3, 122.7] (n=4) | 0.925 sd 0.93 [0, 1.9] (n=4) | 131.51 |
| defrag_cycle_max_ms | 13 sd 0 [13, 13] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| defrag_starts | 10 sd 0 [10, 10] (n=4) | 10 sd 0 [10, 10] (n=4) | 1.00 |
| frag_ratio | 1.81 sd 0 [1.81, 1.81] (n=4) | 1.81 sd 0 [1.81, 1.81] (n=4) | 1.00 |
| active_defrag_hits | 2.111e+05 sd 2.6e+03 [2.079e+05, 2.14e+05] (n=4) | 1.403e+05 sd 1.3e+03 [1.386e+05, 1.421e+05] (n=4) | 1.51 |
| total_active_defrag_time | 3.976e+04 sd 52 [3.968e+04, 3.982e+04] (n=4) | 3.975e+04 sd 24 [3.973e+04, 3.978e+04] (n=4) | 1.00 |
| server_cpu_s | 1.377 sd 0.019 [1.36, 1.41] (n=4) | 1.218 sd 0.013 [1.21, 1.24] (n=4) | 1.13 |
| server_peak_rss_mb | 320.7 sd 0 [320.7, 320.7] (n=4) | 320.7 sd 0.043 [320.6, 320.7] (n=4) | 1.00 |

## Decision check: LATENCY LATEST 3 s after enabling defrag

```
[
 {
  "arm": "parent",
  "latency_latest": [
   [
    "b'command'",
    "1793293462",
    "653",
    "653"
   ],
   [
    "b'active-defrag-cycle'",
    "1793293465",
    "14",
    "14"
   ]
  ],
  "active_defrag_running": "1"
 },
 {
  "arm": "fix",
  "latency_latest": [
   [
    "b'command'",
    "1793293468",
    "631",
    "631"
   ]
  ],
  "active_defrag_running": "1"
 }
]
```

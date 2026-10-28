# valkey blind-to-target-overload: parent 501b3153f26e vs fix 262b371da0d2

One sorted set: 2,000,000 members added, all but 1 removed by one ZREMRANGEBYRANK, then a burst of 200,000 new members in pipelined ZADD batches of 100 (measured). mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| burst_s | 1.236 sd 0.19 [1.051, 1.571] (n=5) | 0.9696 sd 0.0051 [0.964, 0.979] (n=5) | 1.28 |
| inserts_per_s | 1.654e+05 sd 2.3e+04 [1.273e+05, 1.903e+05] (n=5) | 2.063e+05 sd 1e+03 [2.043e+05, 2.074e+05] (n=5) | 0.80 |
| batch_us_p50 | 386.3 sd 1.1 [384.6, 387.7] (n=5) | 376.9 sd 1.9 [375.2, 380.4] (n=5) | 1.02 |
| batch_us_p99 | 2515 sd 1.1e+03 [1050, 4038] (n=5) | 468.4 sd 27 [433.5, 511.1] (n=5) | 5.37 |
| batch_us_max | 4538 sd 9.5e+02 [2965, 5776] (n=5) | 1648 sd 9.2e+02 [586.2, 2938] (n=5) | 2.75 |
| server_cpu_s | 0.536 sd 0.19 [0.35, 0.87] (n=5) | 0.266 sd 0.008 [0.26, 0.28] (n=5) | 2.02 |
| server_peak_rss_mb | 167.7 sd 0.27 [167.3, 168.1] (n=5) | 167.8 sd 0.33 [167.3, 168.2] (n=5) | 1.00 |
| fill_s | 9.118 sd 0.069 [9.01, 9.21] (n=5) | 9.17 sd 0.057 [9.08, 9.24] (n=5) | 0.99 |
| remove_s | 0.228 sd 0.0075 [0.22, 0.24] (n=5) | 0.234 sd 0.008 [0.23, 0.25] (n=5) | 0.97 |

parent, before the burst: `Hash table 0 stats (main hash table): | table size: 3670016 | number of entries: 1 | rehashing index: 0 | top-level buckets: 524288 | child buckets: 0 | max chain length: 0 | avg chain length: 0.000000 | chain length distribution: | 0: 524288 (100.00%) | Hash table 1 stats (rehashing target): | table size: 7 | number of entries: 0 | top-level buckets: 1 | child buckets: 0 | max chain length: 0 | avg chain length: 0.000000 | chain length distribution: | 0: 1 (100.00%)`

parent, after: `Hash table 0 stats (main hash table): | table size: 229376 | number of entries: 200001 | rehashing index: -1 | top-level buckets: 32768 | child buckets: 8949 | max chain length: 2 | avg chain length: 0.273102 | chain length distribution: | 0: 23962 (73.13%) | 1: 8663 (26.44%) | 2: 143 (0.44%)`

fix, before the burst: `Hash table 0 stats (main hash table): | table size: 3670016 | number of entries: 1 | rehashing index: 0 | top-level buckets: 524288 | child buckets: 0 | max chain length: 0 | avg chain length: 0.000000 | chain length distribution: | 0: 524288 (100.00%) | Hash table 1 stats (rehashing target): | table size: 7 | number of entries: 0 | top-level buckets: 1 | child buckets: 0 | max chain length: 0 | avg chain length: 0.000000 | chain length distribution: | 0: 1 (100.00%)`

fix, after: `Hash table 0 stats (main hash table): | table size: 3670016 | number of entries: 200001 | rehashing index: -1 | top-level buckets: 524288 | child buckets: 0 | max chain length: 0 | avg chain length: 0.000000 | chain length distribution: | 0: 524288 (100.00%)`

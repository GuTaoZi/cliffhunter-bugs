# rank 8, rocksdb/marking-ignores-progress: parent 6dbb6f30e604 vs fix f7b791b213b2

preserve_internal_time_seconds=100, writes spread over 20 s, the file moved to the last level (6); then 30 s with no requests. mean, sd [min, max] over 5 runs per arm.

| metric | parent | fix |
|---|---|---|
| compactions_in_window | 429.4 sd 2.9 [425, 433] (n=5) | 0 sd 0 [0, 0] (n=5) |
| compaction_output_mb_in_window | 985.5 sd 6.8 [975.4, 993.8] (n=5) | 0 sd 0 [0, 0] (n=5) |
| cpu_s | 26.83 sd 0.064 [26.77, 26.94] (n=5) | 0.001 sd 0 [0.001, 0.001] (n=5) |
| peak_rss_mb | 24.56 sd 0.26 [24.1, 24.8] (n=5) | 21.28 sd 0.2 [20.9, 21.5] (n=5) |
| manifest_bytes_before | 940 sd 0 [940, 940] (n=5) | 940 sd 0 [940, 940] (n=5) |
| manifest_bytes_after | 5.346e+04 sd 3.8e+02 [5.29e+04, 5.388e+04] (n=5) | 940 sd 0 [940, 940] (n=5) |
| compaction reasons (reason:count) | 1:1,11:425 | 1:1 |

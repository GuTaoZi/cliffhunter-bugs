# Bottommost-files compaction loops: parent vs fix, 30 s idle window after the setup

Setup: 100,000 keys of 1,000 B written twice, flushed, moved to L1, one more key flushed, a snapshot taken and released; then 30 s with no requests. mean, sd [min, max] over 5 runs per arm.

## rank 9, rocksdb/marking-ignores-progress-3 (allow_ingest_behind): parent 00d697bdc532 vs fix eca47fb6960e

| metric | parent | fix |
|---|---|---|
| compactions_in_window | 217.8 sd 3.4 [213, 222] (n=5) | 0 sd 0 [0, 0] (n=5) |
| compaction_output_mb_in_window | 1376 sd 22 [1346, 1402] (n=5) | 0 sd 0 [0, 0] (n=5) |
| cpu_s | 21.23 sd 0.23 [20.99, 21.54] (n=5) | 0 sd 0 [0, 0] (n=5) |
| peak_rss_mb | 20.1 sd 0.33 [19.7, 20.7] (n=5) | 16.72 sd 0.075 [16.6, 16.8] (n=5) |
| manifest_bytes_after | 2.8e+04 sd 4.3e+02 [2.739e+04, 2.853e+04] (n=5) | 881 sd 0 [881, 881] (n=5) |
| compaction reasons (all runs, reason:count) | 1:1,11:222 | 1:1 |

## rank 8, rocksdb/marking-ignores-progress (preserve_internal_time_seconds=10000): parent 6dbb6f30e604 vs fix f7b791b213b2

| metric | parent | fix |
|---|---|---|
| compactions_in_window | 2 sd 0 [2, 2] (n=5) | 1.6 sd 0.8 [0, 2] (n=5) |
| compaction_output_mb_in_window | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |
| cpu_s | 0 sd 0 [0, 0] (n=5) | 0 sd 0 [0, 0] (n=5) |
| peak_rss_mb | 21.42 sd 0.12 [21.2, 21.5] (n=5) | 21.32 sd 0.12 [21.2, 21.5] (n=5) |
| manifest_bytes_after | 1660 sd 0 [1660, 1660] (n=5) | 1660 sd 0 [1660, 1660] (n=5) |
| compaction reasons (all runs, reason:count) | 1:1,2:5 | 1:1,2:5 |

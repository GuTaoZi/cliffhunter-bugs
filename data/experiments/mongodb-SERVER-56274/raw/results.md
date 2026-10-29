# SERVER-56274: index seek past invisible entries, MongoDB 7.0.45 vs 8.2.12

A single-node replica set; 1,000 documents, a snapshot transaction, then 1,000,000 more documents it cannot see at the tail of the _id index. seek: 50 queries find({_id: {$gt: 5e6}}).hint({_id: 1}).limit(1) in the transaction; control: 50 of find().sort({_id: -1}).limit(1). Client latency per query, the server's CPU per query and peak RSS over the loop, and per query the WiredTiger cursor counters (d_*: delta per query). mean, sd [min, max] over repetitions.

| metric | 7.0.45 (unbounded) | 8.2.12 (bounded) | 7.0.45 / 8.2.12 |
|---|---|---|---|
| seek_mean_ms | 1359 sd 74 [1303, 1464] (n=3) | 0.1873 sd 0.066 [0.09684, 0.2529] (n=3) | 7257.02 |
| seek_p50_ms | 1364 sd 82 [1303, 1479] (n=3) | 0.179 sd 0.065 [0.09092, 0.2462] (n=3) | 7618.60 |
| seek_max_ms | 1373 sd 82 [1305, 1489] (n=3) | 0.4726 sd 0.12 [0.3036, 0.5697] (n=3) | 2904.65 |
| seek_server_cpu_ms_per_query | 1368 sd 74 [1313, 1473] (n=3) | 0.3333 sd 0.094 [0.2, 0.4] (n=3) | 4103.40 |
| seek_server_peak_rss_mb | 479.8 sd 9.2 [471.5, 492.7] (n=3) | 484.6 sd 6.4 [477.3, 493] (n=3) | 0.99 |
| seek_d_Total number of entries skipped by cursor next calls | 1e+06 sd 0 [1e+06, 1e+06] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| seek_d_Total number of entries skipped by cursor prev calls | 1e+06 sd 0 [1e+06, 1e+06] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| seek_d_cursor next calls that skip greater than or equal to 100 entries | 1 sd 0 [1, 1] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| seek_d_cursor prev calls that skip greater than or equal to 100 entries | 1 sd 0 [1, 1] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| seek_d_cursor search near calls | 1.887e+06 sd 8e+04 [1.823e+06, 1.999e+06] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| control_mean_ms | 675.6 sd 27 [656, 713.7] (n=3) | 622.2 sd 28 [585.7, 654] (n=3) | 1.09 |
| control_p50_ms | 675.6 sd 27 [656.1, 713.5] (n=3) | 621.2 sd 28 [585.3, 652.7] (n=3) | 1.09 |
| control_max_ms | 678.5 sd 27 [657.7, 716.9] (n=3) | 662.9 sd 54 [590.2, 717.9] (n=3) | 1.02 |
| control_server_cpu_ms_per_query | 677.7 sd 28 [656, 716.8] (n=3) | 630.3 sd 29 [593.2, 663] (n=3) | 1.08 |
| control_server_peak_rss_mb | 479.9 sd 9.3 [471.5, 492.8] (n=3) | 484.9 sd 6.3 [477.8, 493.1] (n=3) | 0.99 |
| control_d_Total number of entries skipped by cursor next calls | 0 sd 0 [0, 0] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| control_d_Total number of entries skipped by cursor prev calls | 1e+06 sd 0 [1e+06, 1e+06] (n=3) | 1e+06 sd 0 [1e+06, 1e+06] (n=3) | 1.00 |
| control_d_cursor next calls that skip greater than or equal to 100 entries | 0 sd 0 [0, 0] (n=3) | 0 sd 0 [0, 0] (n=3) |  |
| control_d_cursor prev calls that skip greater than or equal to 100 entries | 1 sd 0 [1, 1] (n=3) | 1 sd 0 [1, 1] (n=3) | 1.00 |
| control_d_cursor search near calls | 9.441e+05 sd 4e+04 [9.123e+05, 1e+06] (n=3) | 8.614e+05 sd 3.8e+04 [8.123e+05, 9.038e+05] (n=3) | 1.10 |

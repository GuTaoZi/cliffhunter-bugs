# valkey blind-to-target-overload: parent 501b3153f26e vs fix 262b371da0d2

One sorted set: 2,000,000 members added, all but 1 removed by one ZREMRANGEBYRANK, then a burst of 200,000 new members in pipelined ZADD batches of 100 (measured). mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| burst_s | 0.9996 sd 0.34 [0.64, 1.645] (n=5) | 0.8134 sd 0.18 [0.491, 0.953] (n=5) | 1.23 |
| inserts_per_s | 2.206e+05 sd 6.3e+04 [1.216e+05, 3.124e+05] (n=5) | 2.623e+05 sd 7.6e+04 [2.098e+05, 4.072e+05] (n=5) | 0.84 |
| batch_us_p50 | 270.3 sd 98 [152.1, 389.6] (n=5) | 323.4 sd 61 [220.2, 373.5] (n=5) | 0.84 |
| batch_us_p99 | 2772 sd 1.3e+03 [610.2, 4348] (n=5) | 423.3 sd 87 [258.4, 504.3] (n=5) | 6.55 |
| batch_us_max | 4153 sd 1.7e+03 [1850, 6806] (n=5) | 1230 sd 9.4e+02 [590.5, 3022] (n=5) | 3.38 |
| server_cpu_s | 0.556 sd 0.23 [0.3, 0.93] (n=5) | 0.262 sd 0.012 [0.24, 0.27] (n=5) | 2.12 |
| server_peak_rss_mb | 167.9 sd 0.24 [167.5, 168.2] (n=5) | 167.8 sd 0.35 [167.2, 168.2] (n=5) | 1.00 |
| fill_s | 7.238 sd 1.3 [5.59, 9.2] (n=5) | 8.234 sd 0.87 [6.64, 9.1] (n=5) | 0.88 |
| remove_s | 0.23 sd 0.0089 [0.22, 0.24] (n=5) | 0.232 sd 0.0098 [0.22, 0.25] (n=5) | 0.99 |

parent, before the burst: `ERR DEBUG command not allowed. If the enable-debug-command option is set to "local", you can run it from a local connection, otherwise you need to set this option in the configuration file, and then restart the server.`

parent, after: `ERR DEBUG command not allowed. If the enable-debug-command option is set to "local", you can run it from a local connection, otherwise you need to set this option in the configuration file, and then restart the server.`

fix, before the burst: `ERR DEBUG command not allowed. If the enable-debug-command option is set to "local", you can run it from a local connection, otherwise you need to set this option in the configuration file, and then restart the server.`

fix, after: `ERR DEBUG command not allowed. If the enable-debug-command option is set to "local", you can run it from a local connection, otherwise you need to set this option in the configuration file, and then restart the server.`

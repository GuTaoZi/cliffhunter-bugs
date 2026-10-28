# SERVER-18777: rooted $or branches cached without a trial (MongoDB 8.2.12)

Six arrival orders of class A and class B queries per arm. Latency: the quiet passes (no profiler), per-class median and maximum wall time per query (ms), mean over repetitions; slow: queries that examined more than 100,000 documents (traced passes). Server CPU and peak memory: per pass, from the mongod unit's cgroup.

| order | arm | A median ms | A max ms | B median ms | B max ms | slow A | slow B | multiplans | replans |
|---|---|---|---|---|---|---|---|---|---|
| alternating | orjoin | 143.2 | 215.9 | 2.1 | 2.8 | 17.0 | 0.0 | 2.0 | 0.0 |
| alternating | whole | 1.8 | 2.8 | 1.8 | 2.0 | 0.0 | 0.0 | 36.0 | 34.0 |
| alternating | plain | 1.3 | 2.3 | 1.3 | 1.6 | 0.0 | 0.0 | 36.0 | 34.0 |
| blocked_AB | orjoin | 1.8 | 2.4 | 143.3 | 156.2 | 0.0 | 18.0 | 2.0 | 0.0 |
| blocked_AB | whole | 1.0 | 2.0 | 1.0 | 2.0 | 0.0 | 0.0 | 7.0 | 5.0 |
| blocked_AB | plain | 0.8 | 1.7 | 0.8 | 1.6 | 0.0 | 0.0 | 7.0 | 5.0 |
| blocked_BA | orjoin | 143.1 | 172.3 | 1.7 | 2.1 | 18.0 | 0.0 | 2.0 | 0.0 |
| blocked_BA | whole | 1.1 | 2.0 | 1.1 | 2.1 | 0.0 | 0.0 | 7.0 | 5.0 |
| blocked_BA | plain | 0.9 | 1.7 | 0.9 | 1.7 | 0.0 | 0.0 | 7.0 | 5.0 |
| shuffled | orjoin | 143.3 | 155.7 | 2.2 | 3.2 | 17.0 | 0.0 | 2.0 | 0.0 |
| shuffled | whole | 2.0 | 3.2 | 1.6 | 2.4 | 0.0 | 0.0 | 19.0 | 17.0 |
| shuffled | plain | 1.6 | 2.0 | 1.4 | 2.1 | 0.0 | 0.0 | 19.0 | 17.0 |
| pair_AAB | orjoin | 2.4 | 2.6 | 154.1 | 154.1 | 0.0 | 1.0 | 2.0 | 0.0 |
| pair_AAB | whole | 2.1 | 2.3 | 2.5 | 2.5 | 0.0 | 0.0 | 3.0 | 1.0 |
| pair_AAB | plain | 1.7 | 1.9 | 2.7 | 2.7 | 0.0 | 0.0 | 3.0 | 1.0 |
| pair_BBB | orjoin | - | - | 2.0 | 2.3 | - | 0.0 | 2.0 | 0.0 |
| pair_BBB | whole | - | - | 1.9 | 2.3 | - | 0.0 | 2.0 | 0.0 |
| pair_BBB | plain | - | - | 1.6 | 1.9 | - | 0.0 | 2.0 | 0.0 |

| arm | passes | server CPU s per pass (quiet) | server peak MB (quiet) | queries' wall s per pass (quiet) |
|---|---|---|---|---|
| orjoin | 3 | 10.29 | 269 | 10.47 |
| whole | 3 | 0.16 | 269 | 0.23 |
| plain | 3 | 0.13 | 269 | 0.18 |

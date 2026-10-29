# redis no-yield-feedback: parent dcd0b3d02013 vs fix f86575f210a9

200,000 module values of 400 bytes, every other one deleted (fragmentation the scan cannot move), defrag on at t=0 for 80 s with a PING every 1 ms. wA_*: the window from A s ([0,10), [10,40), [45,75)); effort_mean: INFO active_defrag_running (percent of each tick), main_cpu_frac: main-thread CPU per second. mean, sd [min, max].

| metric | parent | fix | parent / fix |
|---|---|---|---|
| frag_ratio_before | 1.95 sd 0 [1.95, 1.95] (n=4) | 1.95 sd 0 [1.95, 1.95] (n=4) | 1.00 |
| threshold_upper | 85 sd 0 [85, 85] (n=4) | 85 sd 0 [85, 85] (n=4) | 1.00 |
| w0_effort_mean | 46.25 sd 2.2 [45, 50] (n=4) | 23.73 sd 1.2 [21.8, 24.7] (n=4) | 1.95 |
| w0_raw_p50_ms | 0.051 sd 0 [0.051, 0.051] (n=4) | 0.05125 sd 0.00043 [0.051, 0.052] (n=4) | 1.00 |
| w0_cor_p50_ms | 0.112 sd 0 [0.112, 0.112] (n=4) | 0.1115 sd 0.0005 [0.111, 0.112] (n=4) | 1.00 |
| w0_cor_p99_ms | 48.82 sd 0.15 [48.66, 48.97] (n=4) | 39.58 sd 1.8 [36.39, 40.65] (n=4) | 1.23 |
| w0_raw_max_ms | 50.83 sd 0.016 [50.81, 50.85] (n=4) | 50.85 sd 0.022 [50.83, 50.89] (n=4) | 1.00 |
| w0_raw_over_10ms | 69.25 sd 0.43 [69, 70] (n=4) | 74.75 sd 0.83 [74, 76] (n=4) | 0.93 |
| w0_main_cpu_frac | 0.3162 sd 0.0032 [0.3115, 0.3198] (n=4) | 0.2164 sd 0.0091 [0.2019, 0.2243] (n=4) | 1.46 |
| w10_effort_mean | 50 sd 0 [50, 50] (n=4) | 5.825 sd 0.54 [4.933, 6.267] (n=4) | 8.58 |
| w10_raw_p50_ms | 0.051 sd 0 [0.051, 0.051] (n=4) | 0.05125 sd 0.00043 [0.051, 0.052] (n=4) | 1.00 |
| w10_cor_p50_ms | 0.112 sd 0 [0.112, 0.112] (n=4) | 0.1113 sd 0.00043 [0.111, 0.112] (n=4) | 1.01 |
| w10_cor_p99_ms | 48.71 sd 0.08 [48.64, 48.84] (n=4) | 6.455 sd 0.66 [5.352, 6.961] (n=4) | 7.55 |
| w10_raw_max_ms | 50.85 sd 0.018 [50.83, 50.88] (n=4) | 12.95 sd 1.2 [10.82, 13.79] (n=4) | 3.93 |
| w10_raw_over_10ms | 208 sd 0.71 [207, 209] (n=4) | 22.75 sd 11 [5, 32] (n=4) | 9.14 |
| w10_main_cpu_frac | 0.3115 sd 0.0043 [0.3049, 0.317] (n=4) | 0.07381 sd 0.0046 [0.06649, 0.07821] (n=4) | 4.22 |
| w45_effort_mean | 50 sd 0 [50, 50] (n=4) | 2.008 sd 0.092 [1.9, 2.1] (n=4) | 24.90 |
| w45_raw_p50_ms | 0.051 sd 0 [0.051, 0.051] (n=4) | 0.05125 sd 0.00043 [0.051, 0.052] (n=4) | 1.00 |
| w45_cor_p50_ms | 0.112 sd 0 [0.112, 0.112] (n=4) | 0.111 sd 0 [0.111, 0.111] (n=4) | 1.01 |
| w45_cor_p99_ms | 48.69 sd 0.077 [48.64, 48.83] (n=4) | 2.073 sd 0.35 [1.582, 2.465] (n=4) | 23.49 |
| w45_raw_max_ms | 50.84 sd 0.01 [50.82, 50.85] (n=4) | 3.493 sd 0.39 [2.864, 3.834] (n=4) | 14.55 |
| w45_raw_over_10ms | 208 sd 1 [207, 209] (n=4) | 0 sd 0 [0, 0] (n=4) |  |
| w45_main_cpu_frac | 0.3134 sd 0.0014 [0.3119, 0.3157] (n=4) | 0.04101 sd 0.0013 [0.03895, 0.04205] (n=4) | 7.64 |
| hits_end | 2.832e+05 sd 3.4e+02 [2.827e+05, 2.836e+05] (n=4) | 2.832e+05 sd 5.5e+02 [2.827e+05, 2.841e+05] (n=4) | 1.00 |
| misses_end | 7.817e+07 sd 3.7e+06 [7.323e+07, 8.363e+07] (n=4) | 1.311e+07 sd 7.6e+04 [1.301e+07, 1.322e+07] (n=4) | 5.96 |
| frag_ratio_end | 1.91 sd 0 [1.91, 1.91] (n=4) | 1.91 sd 0 [1.91, 1.91] (n=4) | 1.00 |
| server_cpu_s | 24.89 sd 0.18 [24.7, 25.18] (n=4) | 5.9 sd 0.22 [5.55, 6.13] (n=4) | 4.22 |
| server_peak_rss_mb | 118.2 sd 0.083 [118.1, 118.3] (n=4) | 118.2 sd 0.11 [118.1, 118.4] (n=4) | 1.00 |

## Decision check (40,000 keys, 20,000 live, 15 s): each arm's pass log

```
parent:
  3507072:M 29 Oct 2026 13:04:35.413 - Starting active defrag, frag=91%, frag_bytes=11129872, cpu=50%
  3507072:M 29 Oct 2026 13:04:35.559 - Active defrag done in 145ms, reallocated=56385, frag=86%, frag_bytes=10600424
  3507072:M 29 Oct 2026 13:04:35.559 - Starting active defrag, frag=86%, frag_bytes=10600424, cpu=50%
  3507072:M 29 Oct 2026 13:04:35.687 - Active defrag done in 128ms, reallocated=292, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:35.688 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:35.815 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:35.816 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:35.943 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:35.944 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:36.071 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:36.071 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:36.199 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:36.200 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:36.327 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
  3507072:M 29 Oct 2026 13:04:36.327 - Starting active defrag, frag=86%, frag_bytes=10579944, cpu=50%
  3507072:M 29 Oct 2026 13:04:36.455 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10579944
fix:
  3507328:M 29 Oct 2026 13:04:52.692 - Starting active defrag, frag=90%, frag_bytes=11112960, cpu=50%
  3507328:M 29 Oct 2026 13:04:52.838 - Active defrag done in 144ms, reallocated=55177, frag=86%, frag_bytes=10600168
  3507328:M 29 Oct 2026 13:04:52.838 - Starting active defrag, frag=86%, frag_bytes=10600168, cpu=50%
  3507328:M 29 Oct 2026 13:04:52.966 - Active defrag done in 127ms, reallocated=131, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:52.966 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=47%
  3507328:M 29 Oct 2026 13:04:53.094 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:53.094 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=42%
  3507328:M 29 Oct 2026 13:04:53.222 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:53.222 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=38%
  3507328:M 29 Oct 2026 13:04:53.350 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:53.350 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=34%
  3507328:M 29 Oct 2026 13:04:53.478 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:53.478 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=31%
  3507328:M 29 Oct 2026 13:04:53.606 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
  3507328:M 29 Oct 2026 13:04:53.606 - Starting active defrag, frag=86%, frag_bytes=10596072, cpu=28%
  3507328:M 29 Oct 2026 13:04:53.734 - Active defrag done in 127ms, reallocated=0, frag=86%, frag_bytes=10596072
```

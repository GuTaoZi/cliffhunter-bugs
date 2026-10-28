| run | wall s | server CPU s | peak RSS MB | query millis | docs examined | hits | misses | replanned | evicted | inactive_replaced | mp_count | mp_micros | mp_works | final cache entry |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| s107471-P_first-r1 | 24.66 | 19.07 | 753 | 17,327 | 27,164,400 | 1,798 | 3 | 0 | 0 | 0 | 2 | 60,322 | 20,000 | active, works 5274, indexField1_1 |
| s107471-P_first-r2 | 23.57 | 18.63 | 817 | 16,937 | 27,164,400 | 1,798 | 3 | 0 | 0 | 0 | 2 | 55,180 | 20,000 | active, works 5274, indexField1_1 |
| s107471-R_first-r1 | 18.87 | 13.35 | 816 | 11,053 | 3,165,600 | 1,199 | 602 | 150 | 0 | 149 | 751 | 10,247,528 | 6,000,604 | inactive, works 32, indexField1_1 |
| s107471-R_first-r2 | 18.97 | 13.41 | 811 | 11,169 | 3,165,600 | 1,199 | 602 | 150 | 0 | 149 | 751 | 10,513,629 | 6,000,604 | inactive, works 32, indexField1_1 |
| s79039-alternating-r1 | 45.19 | 40.66 | 771 | 38,661 | 36,003,600 | 719 | 722 | 719 | 0 | 0 | 1,440 | 38,856,401 | 72,010,080 | inactive, works 12, a_1 |
| s79039-alternating-r2 | 44.9 | 40.48 | 810 | 38,776 | 36,003,600 | 719 | 722 | 719 | 0 | 0 | 1,440 | 38,904,876 | 72,010,080 | inactive, works 12, a_1 |
| s79039-blocked_EC-r1 | 26.08 | 21.29 | 728 | 20,135 | 36,003,600 | 1,438 | 3 | 0 | 0 | 0 | 2 | 188,299 | 200,004 | active, works 50001, a_1 |
| s79039-blocked_EC-r2 | 25.68 | 21.18 | 811 | 19,940 | 36,003,600 | 1,438 | 3 | 0 | 0 | 0 | 2 | 176,203 | 200,004 | active, works 50001, a_1 |

# SERVER-107471: the ticket and its discussion

<https://jira.mongodb.org/browse/SERVER-107471>, read from the public Jira API on 2026-10-27 (all fields, with the
change history). People are named by role.

| | |
|---|---|
| Title | Query Plan Cache Issue with Index Selection on High Disparity Index Values |
| Type, priority | Bug, Major - P3 |
| Filed | 2025-07-14, by a community user; affects 4.4.13 and 4.4.29 |
| Closed | 2025-08-20, Won't Do; 5 watchers, 0 votes |

**What the reporter wrote.** A query with `skip` and the same query without it get the same `queryHash` and
`planCacheKey`. A plan cached from the skip query (its winner uses the `_id` index) is then reused for a selective
value such as `{"indexField10": NumberLong(93333)}`, which matches one document and should use the `indexField10`
index. The reporter expected the planner to update the cached plan when the queried value is that selective.

**The discussion.** Two comments.

- 2025-07-18, the reporter, walking through six steps of the cache's life: the first query is planned and cached
  inactive; the second, identical, activates it; the third, fourth and fifth reuse it after 59,100, 50,100 and
  100,000 works, each judged satisfactory because it returned enough documents (101) or reached the end of the
  scan. The trial bound is `maxWorksBeforeReplan = internalQueryCacheEvictionRatio (10) x decisionWorks`, here
  30,000 x 10, "therefore, even if 10,000 documents are scanned using the `_id` index, the query system still
  considers this query plan to be efficient."
- 2025-08-20, the assignee (MongoDB): "MongoDB 4.4 reached end of life on February 29, 2024 and is no longer
  supported. Can you please upgrade to MongoDB v7.0+ and see if your issue reoccurs?" The ticket was closed as
  Won't Do the same minute, without the retest.

**What this means for us.** The ticket was closed on the version, not on the mechanism, and nobody checked a
supported release. Our reproduction (`../../../../experiments/existing-tools/2026-09-21-jira-repro/README.md`) shows
it on 8.2.12 with default knobs: the rare query reads about 20,000x the documents it needs and the server spends
1.8x the time, by arrival order alone (the skip query first vs the selective query first), because the trial run's
bound accepts the wrong plan.

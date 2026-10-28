# SERVER-79039: the ticket and its discussion

<https://jira.mongodb.org/browse/SERVER-79039>, read from the public Jira API on 2026-10-27 (all fields, with the
change history). People are named by role.

| | |
|---|---|
| Title | Plan cache entries can be evicted and replanned continuously for certain workload patterns |
| Type, priority | Improvement, Major - P3 |
| Filed | 2023-07-17, by a MongoDB engineer |
| Closed | 2023-08-17, Won't Do; 10 watchers, 0 votes; no affected or fix version recorded |

**What the reporter wrote.** For some query patterns the plan cache runs a cycle of cache, evict, replan, cache
"for the same query shape and same plan depending on the parameters". Replanning needs a 10x increase in works
(seen in slow-query logs as `"replanReason":"cached plan was less efficient than expected: expected trial execution
to take X reads but it took at least Y reads"`). After the expensive query evicts the entry it stays *inactive*;
if the next query to activate it has a lower works value, that value is used, "its like the higher work query
never happened", and the eviction can repeat. The reporter notes that inactive entries exist for the opposite case
(a sub-optimal, very high works plan getting cached; SERVER-32452).

**The discussion.** One comment, on 2023-07-21, from a query-team engineer to the reporter, after talking it over
with a second engineer: "We agree the changes to the replanning behaviour are too risky but in terms of
diagnosability we could consider adding the original plan when a replanning happens."

**History.** 2023-07-17 the reporter moved it to Needs Scheduling; 2023-07-20 a triager assigned it out of the
query-optimization backlog and set Investigating; 2023-07-27 it was reassigned; 2023-08-17 the assignee closed it
as Won't Do. No linked tickets; no later follow-up on the diagnosability suggestion is recorded on the ticket.

**What this means for us.** The vendor did not dispute the mechanism; it declined to change it for risk. Our
reproduction (`../../../../experiments/existing-tools/2026-09-21-jira-repro/README.md`) shows the cycle on 8.2.12
with every plan-cache knob at its default: 23 replans vs 0 and 12.3x optimizer CPU between two arrival orders of
the same queries, and the boundary where the mechanism predicts it (the expensive class's works above 10x the cheap
class's).

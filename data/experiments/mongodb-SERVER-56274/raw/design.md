All code claims below come from reading the clones. Nothing was executed, so every timing and counter figure is a prediction from the code, not a measurement. Hashes are 12-char. `W` means `src/third_party/wiredtiger`, `WTS` means `src/mongo/db/storage/wiredtiger`.

## 0. Corrections to the project notes (read first)

- **SERVER-55750 is unrelated.** It is `featureFlagBatchMultiDeletes` (batched multi-deletes): `src/mongo/db/storage/storage_parameters.idl:148-152@c4c3546f9dd0`. The commit, "Enable featureFlagBatchMultideletes", set `default: true`, `version: 6.1`, and first shipped in r6.1.0-rc0. Nothing gates bounded cursors on any flag.
- **SERVER-65528 is only one part of the fix.** Its commit is titled "Set bounds when restoring index cursors" and covers only the index-cursor restore path.
- **SERVER-56274 appears nowhere.** `git log --all --grep` and `-S` over the server clone, and `--grep` over the WiredTiger clone, find no mention. I could not read the ticket, so the mechanism below is derived from code, not from the ticket.
- **The fix is in the server, on top of a WiredTiger API.** The `WT_CURSOR::bound` API was added to WiredTiger by WT-9135 (`src/include/wiredtiger.in`, 9f4c18f7d9ed, 2022-05-11). It is absent from r6.0.29 (33f30ee3b0d8) and present at `wiredtiger.in:698@290112ef1396` (r6.2.0). The skip counters come from WT-6329 (7b9ea6ebf72c).

## 1. The fix: commits and releases

No commit below touches an `.idl` file or a flag. The `bound()` calls are unconditional.

| Ticket | Commit | What it does | First tag (by date) | Release lines |
|---|---|---|---|---|
| SERVER-65528 | 790dde10c5f6 (2022-09-14) | Bounds the index-cursor restore, `wiredtiger_index.cpp:1059-1090@790dde10c5f6`. Its comment names the cost of search_near over deleted keys, "e.g. TTL deletes". | r6.2.0-rc0 | v6.2, v6.3, v7.0 and later. NOT v6.0, v5.0 or v4.4: no backport, and r6.0.29 has zero `bound(` in `WTS/wiredtiger_index.cpp`. |
| SERVER-65527 | 41efbd3eb4c7 (2022-10-26) | Unique-index duplicate check: `_keyExistsBounded`, `wiredtiger_index.cpp:525-585@41efbd3eb4c7`. | r6.2.0-rc0 | same as above |
| SERVER-69093 | a2e3317f15df (2023-06-22) | Bounds the record-store cursor restore, `wiredtiger_record_store.cpp:2315-2330@a2e3317f15df`. Its comment says "capped collections ... a lot of deletes". | r7.1.0-alpha0 | v7.1, v7.2, v7.3, v8.0 and later. NOT v7.0: `wiredtiger_record_store.cpp:2168-2195@b345c2303bcb` (r7.0.45) still uses an unbounded `search_near`. |
| SERVER-68380 | 1fa8459ee823 (2024-01-16) | "Always use bounded cursors": every index seek and restore is bounded. | r7.3.0-alpha1 | v7.3, v8.0 and later. NOT v7.0 or v7.2. |
| SERVER-85261 and SERVER-85465 | 0dbbf6cacf89, d78d6a5e5713 (Feb 2024) | RecordStore bounded `seek` API. Replaces `seekNear` in collection scans: `collection_scan.cpp:254@b345c2303bcb` (r7.0.45) calls `seekNear`; no `seekNear` remains in `src/mongo` at 10d50f5046de. | r8.0.0-alpha0 | v8.0 and later |
| SERVER-88411 | c0ca717b3663 (2024-09-27) | Removes the last `search_near` in the server (oplog reclaim). | r8.1.0-alpha0 | v8.1, v8.2, v8.3, v9.0. NOT v8.0. |

- **Branch checks.** `git log origin/vX --grep=<ticket>` shows 65528 and 65527 in v6.2, v6.3 and v7.0, and 69093 in v7.1 and later. 68380 is in v7.3 and later. Nothing is in v6.0 or v5.0.
- **Binaries you have.** Both contain every fix and have no `search_near(` call anywhere in `src/mongo`. That was checked at 8.2.12 = 10d50f5046de and at 9.1 = 6d990baca59c.
  - 8.2.12: `wiredtiger_index.cpp:968-1006@10d50f5046de`, seek via `bound()` then `cur->next` or `cur->prev`.
  - 9.1: `wiredtiger_index.cpp:1044-1076@6d990baca59c`.

**Which unbounded path the hash-listed shapes hit.** In r7.0.45 (b345c2303bcb), seeks run through `seekWTCursor` into `seekWTCursorInternal(bounded=false)` (`wiredtiger_index.cpp:1176-1193`) and then `search_near` at line 1193. The restore at lines 1062-1086 is already bounded there.

**Why the walk is expensive without bounds.**
- WiredTiger's `search_near` falls back as follows (`W/src/btree/bt_cursor.c:873-905@10d50f5046de`):
  - If the exact key is not visible, it tries `__wt_btcur_next` until it finds a key >= K.
  - If none exists, it resets and does `__wt_btcur_prev`. The code comment reads "We walked to the end of the tree without finding a match. Walk backwards instead."
- The server then runs the SERVER-56839 loop, `wiredtiger_index.cpp:1225-1236@b345c2303bcb`. If `cmp < 0` it calls `advanceWTCursor()`, which is `c->next`. That `next` walks the invisible run forward again.
- So on the unbounded arm, a forward seek past the end walks the trailing invisible run about twice: once `prev`, once `next`.
- With bounds, WiredTiger starts from the bound (`__wti_btcur_bounds_position`, `bt_cursor.c:2303-2360@10d50f5046de`). It walks forward only and exits at the end of the tree, so it costs O(1) in that case.

## 2. The switch

**There is no switch in one binary.**
- I grepped the `.idl` files and the index and record-store sources at 10d50f5046de and 6d990baca59c. There is no server parameter or feature flag for bounded cursors.
- The only storage flags are unrelated ones such as `featureFlagLargeBatchedOperations` (`storage_parameters.idl:249@10d50f5046de`).
- A related parameter once existed but is not this switch: `wiredTigerPrefixSearchForUniqueIndexes`. It was added in 4.4.18 (default false, 17f21f74c517) and 5.0.14 (default true, 61c976882079). It affects only the unique-index insert path, and it is absent from 6.0, 7.0 and 8.x.

**The arms are two release versions.**
- **Fixed arm:** 8.2.12 (10d50f5046de, already installed), or 8.0.34 (a1cb58fa7462) as a closer neighbour. 9.1 also works.
- **Buggy arm:** 7.0.x with x >= 9. The newest tag in the clone is r7.0.45 (b345c2303bcb).
- **Why 7.0.9 or later and not 7.2.x or 6.0.x.** WiredTiger page-skipping (WT-10807, d121cca3b711) shows as three `cursor_tree_walk*del*page_skip` entries in `dist/stat_data.py`.
  - It is absent in r7.0.8, r7.0.0, r7.2.2 (623568a184e2) and r6.0.29 (33f30ee3b0d8).
  - It is present in r7.0.9 (74501701e2e7) and r7.0.45.
  - It is present in r7.3.4 (81c102cee435), r8.0.0 (b41cda4fe697) and 10d50f5046de.
  - So 7.0.45 vs 8.0.34 or 8.2.12 keeps WiredTiger's page-skip logic equal on both arms, and the remaining differences in the walk come from the server's bounded cursors. WiredTiger itself still differs between 7.0 and 8.x, so use the control probe below.
- **Bound-counter caveat.** The `cursor bounds ...` counters exist only in binaries that have the bound API (6.2 or later).

## 3. The workload

### Which shape reaches the unbounded walk

The walk is O(run) when no visible key exists at or beyond the seek key K in the scan direction, and a long run of invisible entries sits right before it.

- **Shape (a), the one to use.** A forward range scan whose lower seek key is past the last visible key, with a run of invisible entries at the tail. Example: `find({_id: {$gt: BIG}}).hint({_id:1}).limit(1)`. The unbounded arm walks the run twice (once `prev`, once `next`); the bounded arm costs O(1).
- **Mirror image.** A descending scan whose upper bound is below all visible keys, with the invisible run at the head.
- **Record-store variant.** A clustered collection (`createCollection("cq", {clusteredIndex: {key: {_id: 1}, unique: true}})`) with `find({_id: {$gt: BIG}})`. In 7.0.x this goes through `CollectionScan` into `seekNear` into an unbounded `search_near` (`collection_scan.cpp:254` and `wiredtiger_record_store.cpp:2034-2058@b345c2303bcb`). In 8.x it uses the bounded `seek` (`wiredtiger_record_store.cpp:1743-1780@10d50f5046de`).

### Shapes that do not discriminate

- **`find().sort({_id:-1}).limit(1)` with a deleted or invisible tail.** Both arms must walk the run to find the last visible key. Use this as the control probe: it should show equal skip counts on both arms.
- **`sort({_id:1}).limit(1)` with a deleted head.** Same: the walk is inherent, and bounds do not help.
- **A forward seek whose K sits just before the run, with live data after it.** Both arms walk the run forward. The unbounded arm adds the `prev` fallback only if nothing visible is found.
- **TTL.** The index-cursor restore is already bounded in 7.0, so 7.0.45 vs 8.2 shows no difference. It differs only between 6.0.x and 6.2 or later. TTL is a weak reproducer anyway, because the unbounded fallback fires only when nothing visible follows the restore key.
- **Oplog and capped collections.** `reclaimOplog` seeks a key that still exists, so it is cheap. A capped-collection restore walks only the head tombstones, which both arms must walk.

### What keeps the entries skippable (robust setup)

Use entries that are invisible to the reader's snapshot, not tombstones.
- An update the reader cannot see (`WT_UPDATE_INVALID`) is counted in the skip total: `bt_curnext.c:189-190@10d50f5046de`.
- It does not increment `page_deleted_count`, so it never triggers forced eviction. That counter increments only for tombstones visible to all, at `bt_curnext.c:195`; forced eviction is at lines 899-905 with `WT_BTREE_DELETE_THRESHOLD`=1000 at `btree.h:51`.
- It is never page-skipped. `__wt_btcur_skip_page` requires a stop aggregate: `btree_inline.h:2182-2290@10d50f5046de`, with `WT_TIME_AGGREGATE_HAS_STOP` at line 2262.

So the entries stay per-entry skippable as long as the reader's snapshot stays open. Do the following on a single-node replica set:

```
mongod --replSet rs0 --port 27117 --dbpath /tmp/arm --wiredTigerCacheSizeGB 2 \
       --setParameter transactionLifetimeLimitSeconds=3600
```
```js
rs.initiate();
const N = 1_000_000, HEAD = 1000;
const t = db.getSiblingDB("t"); t.q.drop();
t.q.insertMany(Array.from({length: HEAD}, (_, j) => ({_id: j + 1, p: 0})));

// 1. open the snapshot and keep it open
const s = db.getMongo().startSession({causalConsistency: false});
s.startTransaction({readConcern: {level: "snapshot"}});
const sq = s.getDatabase("t").q;
sq.findOne({_id: 1});                       // pins the read timestamp

// 2. add the tail on the autocommit connection (invisible to the open snapshot)
for (let b = 0; b < N / 10000; b++)
  t.q.insertMany(Array.from({length: 10000},
      (_, j) => ({_id: HEAD + b * 10000 + j + 1, p: 0})), {ordered: false});

// 3. probes inside the txn, repeated 200 times
const probe = (f) => { const a = Date.now(); for (let i = 0; i < 200; i++) f(); return (Date.now() - a) / 200; };
probe(() => sq.find({_id: {$gt: 5e6}}).hint({_id: 1}).limit(1).toArray());      // P_fix
probe(() => sq.find({}).hint({_id: 1}).sort({_id: -1}).limit(1).toArray());     // P_ctrl
```

Keep all `_id` values numeric, so no string key sorts after K. The snapshot must be established before the inserts.

**Alternative without a transaction:** raise `minSnapshotHistoryWindowInSeconds` (default 300, `snapshot_window_options.idl:36-42@10d50f5046de`). Take `t0 = db.getSiblingDB("local").oplog.rs.find().sort({$natural:-1}).limit(1).next().ts` before the inserts, then run `db.runCommand({find: "q", filter: {_id: {$gt: 5e6}}, hint: {_id: 1}, limit: 1, readConcern: {level: "snapshot", atClusterTime: t0}})`.

**Realistic "deleted tail" variant (transient, standalone).** Insert 200k docs, `deleteMany({_id: {$gt: 1000}})`, then probe once immediately.
- Deleted-but-unreconciled pages stay per-entry skippable only while they are dirty.
- After the first walk, WiredTiger marks pages dirty and evict-soon (`__wt_page_dirty_and_evict_soon`, `bt_curnext.c:903`). Reconciliation then drops the globally visible tombstones, and later probes are fast.
- A clean page whose deletes are all visible to the reader is skipped by page (`btree_inline.h:2182-2290`).
- Syncdelay is capped at 3600 s (`StorageGlobalParams::kMaxSyncdelaySecs`, `storage_options.h:118@10d50f5046de`), so you cannot disable checkpoints.
- Re-create the tombstones before each probe.

## 4. What to measure

- **Latency.**
  - Use the client-side loop mean above.
  - Cross-check with the delta of `serverStatus().opLatencies.reads.latency/ops`.
  - Use `explain("executionStats")` only to confirm the plan is `IXSCAN` on `_id_` with zero keys examined. Its millisecond granularity is too coarse here.
- **CPU.** Read `/proc/<pid>/stat` utime+stime before and after the 200-probe loop.
- **Peak memory.** Read `VmHWM` from `/proc/<pid>/status`. The walk allocates nothing per entry, so I expect parity (dominated by the WiredTiger cache), not a difference.
- **Counters** (`db.serverStatus().wiredTiger.cursor`, and per index `db.q.stats({indexDetails: true}).indexDetails._id_.cursor`). I did not verify that `collStats` still returns `indexDetails` in 8.2, or the `$collStats` equivalent.
  - Names from `dist/stat_data.py:1166-1173@10d50f5046de` and `:1226@6d990baca59c`:
    - `Total number of entries skipped by cursor next calls`
    - `Total number of entries skipped by cursor prev calls`
    - `cursor next calls that skip greater than or equal to 100 entries`
    - `cursor prev calls that skip greater than or equal to 100 entries`
    - `cursor next calls that skip greater than 1 and fewer than 100 entries`
    - `cursor prev calls that skip less than 100 entries`
  - The server-wide name is `cursor search near calls`. The per-index name is `search near calls`.
  - On the 6.0 line the "greater than 1 and fewer than" counter is named "less than 100".
  - `cursor bounds next called on an unpositioned cursor` and `cursor bounds prev called on an unpositioned cursor` exist only on bound-API binaries.
  - Page-level skip counters: `Total number of deleted pages skipped during tree walk`, `Total number of in-memory deleted pages skipped during tree walk`, `Total number of on-disk deleted pages skipped during tree walk`.
  - In `wiredTiger.cache` (not `cursor`): `forced eviction - pages selected because of too many deleted items count`.
- **Expected values per probe, N = 1e6 invisible tail entries.**

| Counter | 7.0.45, `P_fix` | 8.2.12 / 9.1, `P_fix` | Both arms, `P_ctrl` |
|---|---|---|---|
| prev-skip total | about N | about 0 | about N |
| next-skip total | about N (the SERVER-56839 `advanceWTCursor` loop) | about 0 | about 0 |
| `skip >= 100` (prev and next) | +1 each | 0 | +1 on prev only |
| search near calls | +1 | 0, not strictly guaranteed (WiredTiger internals also call it) | not recorded |
| bounds next / prev unpositioned | n/a | next +1 | prev +1 (8.x only) |

- **Expected latency (estimate, not measured).** About 0.1 to 0.3 s per probe for `P_fix` at N=1e6 on 7.0.45, and under 1 ms on 8.2.12. `P_ctrl` should be similar on both arms.
- **Noise.** In a replica set, the oplog readers move the connection-wide counters. Prefer the per-index `_id_` counters, or take deltas in a quiet window.

## 5. Cheap check (under a minute, standalone mongod, no txn)

```js
const K = ["cursor search near calls",
  "Total number of entries skipped by cursor next calls",
  "Total number of entries skipped by cursor prev calls",
  "cursor next calls that skip greater than or equal to 100 entries",
  "cursor prev calls that skip greater than or equal to 100 entries",
  "cursor bounds next called on an unpositioned cursor"];
const snap = () => { const c = db.serverStatus().wiredTiger.cursor; return K.map(k => c[k]); };
db.q.drop();
for (let b = 0; b < 20; b++)
  db.q.insertMany(Array.from({length: 10000}, (_, i) => ({_id: b * 10000 + i + 1})), {ordered: false});
db.q.deleteMany({_id: {$gt: 1000}});          // about 199k tombstones at the tail of the _id index
const a = snap(), t0 = Date.now();
db.q.find({_id: {$gt: 5e6}}).hint({_id: 1}).limit(1).toArray();
printjson({ms: Date.now() - t0, delta: snap().map((v, i) => v - a[i])});
```

- On 7.0.45, the prev-skip and next-skip totals should each rise by about 199k, with `search near calls` +1.
- On 8.2.12 or 9.1, both totals should be about 0.
- Only the first probe counts. Re-running it on the buggy arm may show about 0 skips, because forced eviction heals the pages. That is expected and not a failure of the design.

## 6. Risks

- **Healing by eviction, checkpoint or page skip.** Forced eviction is described in section 3: it applies only to globally visible tombstones, which is why the invisible-entry setup is immune to it. Checkpoints can make pages clean, and a clean fully-deleted page is skipped by page rather than per entry. A page skip in this situation shows up as the page-skip counters moving instead of the entry-skip totals.
- **Planner.** Make sure the plan is `IXSCAN` on `_id_` (use `hint`). 8.x may pick SBE, which goes through the same index cursor `seek`, so the storage path is the same.
- **Missing flag.** This is the biggest design risk. There is no flag, so the arms differ in WiredTiger and server versions (7.0.x uses WiredTiger 10.x; 8.x uses a later WiredTiger). The control probe `P_ctrl` guards against a general slowdown on one arm.
- **K inside live data.** If the seek key is inside live data or just before a run with live data after it, the cost is the same O(run) on both arms and the bug will not show.
- **Snapshot lifetime.** `transactionLifetimeLimitSeconds` defaults to 60 (`transaction_participant.idl:49-57@10d50f5046de`). `minSnapshotHistoryWindowInSeconds` defaults to 300. If either expires mid-run the snapshot is lost and the tail becomes visible.
- **Cache size.** If the dataset exceeds the cache, page reads dominate. Use `--wiredTigerCacheSizeGB 2` or more.
- **Per-entry cost after a checkpoint.** Once the invisible entries are reconciled to disk, each one may need a history-store lookup, which changes the per-entry cost. Take the measurement before any checkpoint, or report both.
- **Counter names differ between versions.** The "skip less than 100" and "greater than 1 and fewer than 100" names differ (r6.0.29 vs r7.0.45 and later), as do the 9.1 page-skip names (`cursor_tree_walk_del_internal_page_skip` and `del_leaf_page_skip`).
- **Unverified ticket.** SERVER-56274 itself could not be read, so the link from the ticket to these code paths is an inference.

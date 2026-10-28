# Environment

```
date          : 2026-09-15T23:19:54-04:00
host          : <host>
kernel        : Linux 6.18.51 x86_64
cpu           : Intel(R) Xeon(R) 6521P
cores         : 48
mem_total     : 125 GB
governor      : schedutil
thp_enabled   : always [madvise] never
thp_defrag    : always defer defer+madvise [madvise] never
mongod        : db version v8.2.12
mongosh       : 2.9.1
mongod_argv   : ~/.nix-profile/bin/mongod --dbpath $CLIFF_DATA/mongo/data/w1 --port 27117 --wiredTigerCacheSizeGB 8 --logpath $CLIFF_DATA/mongo/log/w1.log --bind_ip 127.0.0.1
```

## Knob values read from the running server

```
internalQueryMaxScansToExplode                           = 200
internalQueryCollectionMaxNoOfDocumentsToChooseHashJoin  = 10000
internalQueryCollectionMaxDataSizeBytesToChooseHashJoin  = 104857600
internalQueryCollectionMaxStorageSizeBytesToChooseHashJoin = 104857600
internalQueryDisableLookupExecutionUsingHashJoin         = false
internalDocumentSourceLookupCacheSizeBytes               = 104857600
internalQueryFrameworkControl                            = "trySbeRestricted"
internalQueryPlanEvaluationMaxResults                    = 101
internalQueryPlanRanker                                  = <unavailable: InvalidOptions>
server version                                           = 8.2.12
```

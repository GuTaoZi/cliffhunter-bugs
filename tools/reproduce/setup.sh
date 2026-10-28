#!/bin/sh
# Clone the upstream repositories the builds need into $CLIFF_DATA/src (full clones: builds check out old commits).
#
#   tools/reproduce/setup.sh [SYSTEM...]     default: all five
set -eu
ROOT=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}
mkdir -p "$ROOT/src" "$ROOT/build" "$ROOT/locks"
SYSTEMS="$*"; [ -n "$SYSTEMS" ] || SYSTEMS="memcached postgres redis rocksdb valkey"
for s in $SYSTEMS; do
  case $s in
    memcached) url=https://github.com/memcached/memcached.git ;;
    postgres) url=https://github.com/postgres/postgres.git ;;
    redis) url=https://github.com/redis/redis.git ;;
    rocksdb) url=https://github.com/facebook/rocksdb.git ;;
    valkey) url=https://github.com/valkey-io/valkey.git ;;
    *) echo "unknown system $s"; exit 2 ;;
  esac
  [ -d "$ROOT/src/$s/.git" ] && { echo "$ROOT/src/$s (present)"; continue; }
  git clone "$url" "$ROOT/src/$s"
done

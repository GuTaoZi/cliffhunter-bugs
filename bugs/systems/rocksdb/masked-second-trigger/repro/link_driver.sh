#!/bin/sh
# Link wbm_driver against one arm's release objects (LIB_SOURCES of that commit, built by
# tools/reproduce/build.sh with DEBUG_LEVEL=0: -O2 -DNDEBUG). Writes only into this directory.
#   link_driver.sh SHA12   -> ./wbm_driver-SHA12
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
D=$SCRIPT_DIR
SHA=$1
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/rocksdb-$SHA/src
test -f "$B/../build.ok"
printf 'include %s/src.mk\nall:\n\t@echo $(LIB_SOURCES)\n' "$B" > "$D/print-$SHA.mk"
OBJS=$(cd "$B" && make -s -f "$D/print-$SHA.mk" | tr ' ' '\n' | grep '\.cc$' | sed 's/\.cc$/.o/')
rm -f "$D/librocksdb-$SHA.a"
(cd "$B" && ar rcs "$D/librocksdb-$SHA.a" $OBJS)
. "$B/make_config.mk" 2>/dev/null || true
CXXF="-O2 -DNDEBUG -fno-omit-frame-pointer -momit-leaf-frame-pointer -include cstdint -std=c++11 -DROCKSDB_PLATFORM_POSIX -DROCKSDB_LIB_IO_POSIX -DOS_LINUX -fno-builtin-memcmp -DROCKSDB_FALLOCATE_PRESENT -DSNAPPY -DGFLAGS=gflags -DZLIB -DBZIP2 -DLZ4 -DZSTD -DROCKSDB_MALLOC_USABLE_SIZE -DROCKSDB_PTHREAD_ADAPTIVE_MUTEX -DROCKSDB_BACKTRACE"
echo "$CXXF" > "$D/wbm_driver-$SHA.flags"
nix-shell -p gcc gflags snappy lz4 zstd zlib bzip2 --run "g++ --version | head -1; g++ $CXXF -I$B/include -o $D/wbm_driver-$SHA $D/wbm_driver.cc $D/librocksdb-$SHA.a -lpthread -lrt -lsnappy -lgflags -lz -lbz2 -llz4 -lzstd"
ls -la "$D/wbm_driver-$SHA"

#!/bin/sh
# Link futile_driver against one arm's release objects (LIB_SOURCES of that commit, built by
# tools/reproduce/build.sh with DEBUG_LEVEL=0: -O2, NDEBUG). Writes only into this directory.
#   link_driver.sh SHA12   -> ./futile_driver-SHA12 (+ .flags)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
INENV=$(cd "$(dirname "$0")/../../../../../tools/reproduce" && pwd)/inenv.sh  # Nix or the host's tools
D=$SCRIPT_DIR
SHA=$1
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/rocksdb-$SHA/src
test -f "$B/../build.ok"
printf 'include %s/src.mk\nall:\n\t@echo $(LIB_SOURCES)\n' "$B" > "$D/print-$SHA.mk"
OBJS=$(cd "$B" && make -s -f "$D/print-$SHA.mk" | tr ' ' '\n' | grep '\.cc$' | sed 's/\.cc$/.o/')
for o in $OBJS; do test -f "$B/$o" || { echo "missing $o"; exit 1; }; done
rm -f "$D/librocksdb-$SHA.a"
(cd "$B" && ar rcs "$D/librocksdb-$SHA.a" $OBJS)
# The library's own platform flags (the same -D set the objects were compiled with).
PCXX=$(sed -n 's/^PLATFORM_CXXFLAGS=//p' "$B/make_config.mk")
# Release RocksDB (DEBUG_LEVEL=0) is built with -fno-rtti; the driver subclasses EnvWrapper, so it must match.
CXXF="-O2 -DNDEBUG -fno-rtti -fno-omit-frame-pointer -include cstdint -std=c++11 $PCXX"
echo "$CXXF" > "$D/futile_driver-$SHA.flags"
PLD=$(sed -n 's/^PLATFORM_LDFLAGS=//p' "$B/make_config.mk")  # the build's own link flags (io_uring, when it used it)
"$INENV" "gcc gflags snappy lz4 zstd zlib bzip2" "g++ --version | head -1; g++ $CXXF -I$B/include -o $D/futile_driver-$SHA $D/futile_driver.cc $D/librocksdb-$SHA.a -lpthread -lrt -lsnappy -lgflags -lz -lbz2 -llz4 -lzstd -ldl $PLD"
ls -la "$D/futile_driver-$SHA"

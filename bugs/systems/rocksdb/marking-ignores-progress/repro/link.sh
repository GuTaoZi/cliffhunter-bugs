#!/bin/sh
# Link bottom_loop against one arm's release objects (LIB_SOURCES of that commit, built by tools/reproduce/build.sh
# with DEBUG_LEVEL=0: -O2, NDEBUG, -fno-rtti). The C++ standard and platform -D flags come from the commit's own
# make_config.mk (2022 RocksDB needs C++17, 2026 RocksDB C++20).
#   link.sh SHA12 [EXTRA_CXXFLAGS]   -> ./bottom_loop-SHA12 (+ .flags)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
set -eu
INENV=$(cd "$(dirname "$0")/../../../../../tools/reproduce" && pwd)/inenv.sh  # Nix or the host's tools
D=$SCRIPT_DIR
SHA=$1; EXTRA=${2:-}
B=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/rocksdb-$SHA/src
test -f "$B/../build.ok"
printf 'include %s/src.mk\nall:\n\t@echo $(LIB_SOURCES)\n' "$B" > "$D/print-$SHA.mk"
OBJS=$(cd "$B" && make -s -f "$D/print-$SHA.mk" | tr ' ' '\n' | grep '\.cc$' | sed 's/\.cc$/.o/')
for o in $OBJS; do test -f "$B/$o" || { echo "missing $o"; exit 1; }; done
rm -f "$D/librocksdb-$SHA.a"
(cd "$B" && ar rcs "$D/librocksdb-$SHA.a" $OBJS)
PCXX=$(sed -n 's/^PLATFORM_CXXFLAGS=//p' "$B/make_config.mk")
STD=$(echo "$PCXX" | grep -o -- '-std=[a-z+0-9]*' | head -1)
[ -n "$STD" ] || STD=-std=c++17
CXXF="-O2 -DNDEBUG -fno-rtti -fno-omit-frame-pointer -include cstdint $STD $PCXX $EXTRA"
echo "$CXXF" > "$D/bottom_loop-$SHA.flags"
PLD=$(sed -n 's/^PLATFORM_LDFLAGS=//p' "$B/make_config.mk")  # the build's own link flags (io_uring, when it used it)
"$INENV" "gcc gflags snappy lz4 zstd zlib bzip2 liburing" "g++ --version | head -1; g++ $CXXF -I$B/include -I$B -o $D/bottom_loop-$SHA $D/bottom_loop.cc $D/librocksdb-$SHA.a -lpthread -lrt -lsnappy -lgflags -lz -lbz2 -llz4 -lzstd -ldl $PLD"
ls -la "$D/bottom_loop-$SHA"

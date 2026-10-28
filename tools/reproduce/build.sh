#!/bin/sh
# Build one system at one commit, in release mode, from a clean export of that commit.
#
#   tools/reproduce/build.sh SYSTEM COMMIT [PATCH]   SYSTEM: postgres | redis | valkey | memcached | rocksdb
#
# Source: ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/src/SYSTEM (a full clone).
# Output: ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}/build/SYSTEM-<12-char sha>/  (with PATCH, a file from
#   bugs/systems/, applied with patch -p1 after export: .../SYSTEM-<12-char sha>+<patch name>/, and
#   patch.txt holds the patch's sha256), with
#   src/ (the exported tree, built in place), install/ (PostgreSQL), build.log, build.ok,
#   and flags.txt (compiler and the optimisation flags actually used).
# A build that already has build.ok is not rebuilt. Exit status is the build's.
# GCC 15 defaults to C23, which breaks older C code; CSTD (default gnu11) is passed to C builds.
# GCC >= 10 defaults to -fno-common, which breaks old code that defines globals in headers; C builds
# pass -fcommon. Old memcached builds with -Werror; it is stripped. GCC >= 13 no longer includes
# <cstdint> transitively, which breaks 2022-2023 RocksDB headers, nor <system_error>, which 2020 RocksDB's bundled
# folly needs; both are force-included.
# None of these change program code.
set -eu
SYS=$1; REV=$2; PATCH=${3:-}
ROOT=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}
REPO=$ROOT/src/$SYS
SHA=$(git -C "$REPO" rev-parse "$REV^{commit}")
OUT=$ROOT/build/$SYS-$(echo "$SHA" | cut -c1-12)
[ -n "$PATCH" ] && { PATCH=$(realpath "$PATCH"); OUT=$OUT+$(basename "$PATCH" .patch); }
[ -f "$OUT/build.ok" ] && { echo "$OUT (already built)"; exit 0; }
# A directory without build.ok is a failed attempt; its stale objects must not be reused.
[ -d "$OUT" ] && mv "$OUT" "$OUT.failed.$(date +%s)"
mkdir -p "$OUT/src"
git -C "$REPO" archive "$SHA" | tar -x -C "$OUT/src"
if [ -n "$PATCH" ]; then
  patch -d "$OUT/src" -p1 < "$PATCH"
  sha256sum "$PATCH" > "$OUT/patch.txt"
fi
CSTD=${CSTD:-gnu11}
J=${J:-32}
cd "$OUT/src"
{
  echo "system=$SYS commit=$SHA date=$(date -Is)"
  case $SYS in
    redis|valkey)
      nix-shell -p gcc gnumake pkg-config --run "gcc --version | head -1; make -j$J MALLOC=jemalloc CFLAGS='-std=$CSTD -fcommon' V=1" ;;
    memcached)
      nix-shell -p gcc gnumake autoconf automake libtool libevent pkg-config perl --run \
        "gcc --version | head -1; ./autogen.sh && ./configure CFLAGS='-O2 -g -std=$CSTD -fcommon' && sed -i 's/ -Werror//g' Makefile && make -j$J" ;;
    postgres)
      nix-shell -p gcc gnumake bison flex perl pkg-config zlib --run \
        "gcc --version | head -1; ./configure --prefix=$OUT/install --without-readline --without-icu --without-zlib CFLAGS='-O2 -std=$CSTD -fcommon' && make -j$J && make install" ;;
    rocksdb)
      nix-shell -p gcc gnumake gflags snappy lz4 zstd zlib bzip2 pkg-config perl --run \
        "g++ --version | head -1; DEBUG_LEVEL=0 PORTABLE=1 DISABLE_WARNING_AS_ERROR=1 EXTRA_CXXFLAGS='-include cstdint -include system_error' make -j$J db_bench cache_bench" ;;
    *) echo "unknown system $SYS"; exit 2 ;;
  esac
} > "$OUT/build.log" 2>&1
grep -m1 -oE '(-O[0-3s]|-Og)' "$OUT/build.log" > "$OUT/flags.txt" || true
grep -m1 -E '^gcc|^g\+\+' "$OUT/build.log" >> "$OUT/flags.txt" || true
# RocksDB's make output does not echo compile lines; record the flags stored in the binary instead.
# db_bench embeds "Assertions are enabled" only when built without NDEBUG.
if [ "$SYS" = rocksdb ]; then
  readelf --debug-dump=info db_bench | grep -m1 DW_AT_producer | sed 's/.*: //' >> "$OUT/flags.txt" || true
  echo "assert_warning_in_db_bench=$(strings db_bench | grep -c 'Assertions are enabled' || true)" >> "$OUT/flags.txt"
fi
touch "$OUT/build.ok"
echo "$OUT"

#!/bin/sh
# Build one system at one commit, in release mode, from a clean export of that commit.
#
#   tools/reproduce/build.sh SYSTEM COMMIT [PATCH]   SYSTEM: postgres | redis | valkey | memcached | rocksdb | wiredtiger
#
# Source: $CLIFF_DATA/src/SYSTEM (a full clone; CLIFF_DATA defaults to ${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}).
# Output: $CLIFF_DATA/build/SYSTEM-<12-char sha>/  (with PATCH, a file from
#   bugs/systems/, applied with patch -p1 after export: .../SYSTEM-<12-char sha>+<patch name>/, and
#   patch.txt holds the patch's sha256), with
#   src/ (the exported tree, built in place), install/ (PostgreSQL), build.log, build.ok,
#   and flags.txt (toolchain, compiler and the optimisation flags actually used).
# A build that already has build.ok is not rebuilt. Exit status is the build's; a failed build prints the end of
# its build.log.
# Toolchain (tools/reproduce/inenv.sh): Nix (nix-shell with the packages named below) when nix-shell is installed,
# otherwise the host's compiler and libraries (on Ubuntu or Debian: tools/reproduce/deps-ubuntu.sh); CLIFF_TOOLCHAIN
# chooses. J (default 32) is the number of parallel jobs.
# GCC 15 defaults to C23, which breaks older C code; CSTD (default gnu11) is passed to C builds.
# GCC >= 10 defaults to -fno-common, which breaks old code that defines globals in headers; C builds
# pass -fcommon. Old memcached builds with -Werror; it is stripped. Memcached's autogen.sh before 2015 looks only for
# automake-1.7 to -1.14 by versioned name; AUTOMAKE and ACLOCAL name the installed unversioned ones. GCC >= 13 no longer includes
# <cstdint> transitively, which breaks 2022-2023 RocksDB headers, nor <system_error>, which 2020 RocksDB's bundled
# folly needs, nor <functional>, which 2016-2017 RocksDB's util/thread_local.h needs; all three are force-included.
# RocksDB trees committed before 2018 also get <array> (table/plain_table_key_coding.h) and <sys/sysmacros.h>, which
# glibc >= 2.28 no longer pulls in through <sys/types.h> (util/io_posix.cc's major()/minor()); newer trees do not, as
# a function-like major() macro would clash with their own names. The same flags serve older compilers (Ubuntu
# 24.04's gcc 13). RocksDB is built without io_uring (ROCKSDB_USE_IO_URING=0, and no liburing in either toolchain), as the recorded builds were.
# None of these change program code.
set -eu
SYS=$1; REV=$2; PATCH=${3:-}
ROOT=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}
TOOLS=$(cd "$(dirname "$0")" && pwd)
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
if ! {
  echo "system=$SYS commit=$SHA date=$(date -Is)"
  case $SYS in
    redis|valkey)
      "$TOOLS/inenv.sh" "gcc gnumake pkg-config" "gcc --version | head -1; make -j$J MALLOC=jemalloc CFLAGS='-std=$CSTD -fcommon' V=1" ;;
    memcached)
      "$TOOLS/inenv.sh" "gcc gnumake autoconf automake libtool libevent pkg-config perl" \
        "gcc --version | head -1; AUTOMAKE=automake ACLOCAL=aclocal ./autogen.sh && ./configure CFLAGS='-O2 -g -std=$CSTD -fcommon' && sed -i 's/ -Werror//g' Makefile && make -j$J" ;;
    postgres)
      "$TOOLS/inenv.sh" "gcc gnumake bison flex perl pkg-config zlib" \
        "gcc --version | head -1; ./configure --prefix=$OUT/install --without-readline --without-icu --without-zlib CFLAGS='-O2 -std=$CSTD -fcommon' && make -j$J && make install" ;;
    rocksdb)
      INC='-include cstdint -include system_error -include functional'
      [ "$(git -C "$REPO" show -s --format=%cd --date=format:%Y "$SHA")" -lt 2018 ] && INC="$INC -include array -include sys/sysmacros.h"
      echo "extra_cxxflags=$INC"
      "$TOOLS/inenv.sh" "gcc gnumake gflags snappy lz4 zstd zlib bzip2 pkg-config perl" \
        "g++ --version | head -1; DEBUG_LEVEL=0 PORTABLE=1 DISABLE_WARNING_AS_ERROR=1 ROCKSDB_USE_IO_URING=0 EXTRA_CXXFLAGS='$INC' make -j$J db_bench cache_bench" ;;
    wiredtiger)
      # Trees before 2021 build with autotools (build_posix/reconf); later ones with CMake. Neither enables -Werror
      # unless asked (--enable-strict, ENABLE_STRICT), so old trees build with a new compiler as written.
      if [ -f build_posix/reconf ] && [ ! -f CMakeLists.txt ]; then
        "$TOOLS/inenv.sh" "gcc gnumake autoconf automake libtool pkg-config" \
          "gcc --version | head -1; sh build_posix/reconf && ./configure CFLAGS='-O2 -g -std=$CSTD -fcommon' && make -j$J V=1"
      else
        "$TOOLS/inenv.sh" "gcc gnumake cmake ninja python3 pkg-config" \
          "gcc --version | head -1; cmake -G Ninja -S . -B build -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=1 -DENABLE_SHARED=0 -DENABLE_PYTHON=0 -DENABLE_STRICT=0 -DHAVE_DIAGNOSTIC=0 -DCMAKE_C_FLAGS='-std=$CSTD -fcommon' -DCMAKE_EXPORT_COMPILE_COMMANDS=ON && ninja -C build -v -j$J wt wtperf"
      fi ;;
    *) echo "unknown system $SYS"; exit 2 ;;
  esac
} > "$OUT/build.log" 2>&1; then
  tail -20 "$OUT/build.log" >&2
  echo "build failed: $OUT/build.log" >&2
  exit 1
fi
grep -m1 -oE '(-O[0-3s]|-Og)' "$OUT/build.log" > "$OUT/flags.txt" || true
grep -m1 '^toolchain=' "$OUT/build.log" >> "$OUT/flags.txt" || true
grep -m1 '^extra_cxxflags=' "$OUT/build.log" >> "$OUT/flags.txt" || true
grep -m1 -E '^gcc|^g\+\+' "$OUT/build.log" >> "$OUT/flags.txt" || true
# RocksDB's make output does not echo compile lines; record the flags stored in the binary instead.
# db_bench embeds "Assertions are enabled" only when built without NDEBUG.
if [ "$SYS" = rocksdb ]; then
  readelf --debug-dump=info db_bench | grep -m1 DW_AT_producer | sed 's/.*: //' >> "$OUT/flags.txt" || true
  echo "assert_warning_in_db_bench=$(strings db_bench | grep -c 'Assertions are enabled' || true)" >> "$OUT/flags.txt"
fi
touch "$OUT/build.ok"
echo "$OUT"

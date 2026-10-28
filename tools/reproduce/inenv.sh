#!/bin/sh
# Run one build step with the tools it needs: under nix-shell with the named Nix packages, or directly with the
# host's own tools (on Ubuntu or Debian, installed by tools/reproduce/deps-ubuntu.sh).
#
#   tools/reproduce/inenv.sh "NIX PACKAGES" 'COMMAND'
#
# CLIFF_TOOLCHAIN=nix or host chooses; by default nix when nix-shell is on PATH, host otherwise. On the host the
# Nix package names are only used to check, before the step starts, that what they stand for is installed, and to
# name the apt package that provides it.
set -eu
PKGS=$1
shift
CMD=$*
TC=${CLIFF_TOOLCHAIN:-$(command -v nix-shell >/dev/null 2>&1 && echo nix || echo host)}
case $TC in
  nix)
    echo "toolchain=nix ($PKGS)" >&2
    exec nix-shell -p $PKGS --run "$CMD" ;;
  host) ;;
  *) echo "CLIFF_TOOLCHAIN must be nix or host, not '$TC'" >&2; exit 2 ;;
esac

missing=""
need_cmd() {  # need_cmd COMMAND APT-PACKAGE
  command -v "$1" >/dev/null 2>&1 || missing="$missing $1 (apt: $2)"
}
need_hdr() {  # need_hdr HEADER APT-PACKAGE
  # Preprocessed as C++ (gflags.h is a C++ header), or as C where no C++ compiler is installed.
  if command -v "${CXX:-c++}" >/dev/null 2>&1; then
    printf '#include <%s>\n' "$1" | "${CXX:-c++}" -E -x c++ - >/dev/null 2>&1 || missing="$missing <$1> (apt: $2)"
  else
    printf '#include <%s>\n' "$1" | "${CC:-cc}" -E -x c - >/dev/null 2>&1 || missing="$missing <$1> (apt: $2)"
  fi
}
for p in $PKGS; do
  case $p in
    gcc) need_cmd gcc build-essential; need_cmd g++ build-essential ;;
    gnumake) need_cmd make build-essential ;;
    pkg-config) need_cmd pkg-config pkg-config ;;
    autoconf) need_cmd autoconf autoconf ;;
    automake) need_cmd automake automake ;;
    libtool) need_cmd libtoolize libtool ;;
    bison) need_cmd bison bison ;;
    flex) need_cmd flex flex ;;
    perl) need_cmd perl perl ;;
    perf) need_cmd perf linux-tools-generic ;;
    libevent) need_hdr event.h libevent-dev ;;
    zlib) need_hdr zlib.h zlib1g-dev ;;
    gflags) need_hdr gflags/gflags.h libgflags-dev ;;
    snappy) need_hdr snappy-c.h libsnappy-dev ;;
    lz4) need_hdr lz4.h liblz4-dev ;;
    zstd) need_hdr zstd.h libzstd-dev ;;
    bzip2) need_hdr bzlib.h libbz2-dev ;;
    liburing) ;;  # optional: RocksDB is built without io_uring
    *) ;;
  esac
done
if [ -n "$missing" ]; then
  echo "toolchain=host: missing$missing" >&2
  echo "On Ubuntu or Debian: tools/reproduce/deps-ubuntu.sh installs them all." >&2
  exit 1
fi
echo "toolchain=host" >&2
exec sh -c "$CMD"

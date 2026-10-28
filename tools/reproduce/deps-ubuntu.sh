#!/bin/sh
# Install with apt what the reproductions need on Ubuntu or Debian, the path without Nix: builds then run with the
# host's own compiler and libraries (tools/reproduce/inenv.sh picks the host when nix-shell is absent).
#
#   tools/reproduce/deps-ubuntu.sh [PART...]
#
# PART: memcached postgres redis valkey rocksdb (build tools and libraries for that system), tools (what the run
# scripts call: GNU time, strace, flock, pgrep), perf (the profiler), mongodb (the libraries the MongoDB release
# tarballs link against; tools/reproduce/get-mongodb.sh downloads mongod and mongosh). Default: everything but perf.
# Runs apt-get with sudo unless already root. Tested on Ubuntu 24.04 (gcc 13.3).
set -eu
PARTS=${*:-memcached postgres redis valkey rocksdb tools mongodb}
PKGS="build-essential git pkg-config python3 ca-certificates curl"
for p in $PARTS; do
  case $p in
    memcached) PKGS="$PKGS autoconf automake libtool libevent-dev perl" ;;
    postgres) PKGS="$PKGS bison flex perl zlib1g-dev" ;;
    redis|valkey) ;;  # make, gcc and the bundled jemalloc; nothing more
    rocksdb) PKGS="$PKGS perl libgflags-dev libsnappy-dev liblz4-dev libzstd-dev zlib1g-dev libbz2-dev" ;;  # no liburing: the recorded builds have no io_uring
    tools) PKGS="$PKGS time strace procps util-linux binutils" ;;
    perf)
      # Ubuntu ships perf per kernel; another kernel (a VM, WSL) needs the generic one, Debian calls it linux-perf.
      if apt-cache show "linux-tools-$(uname -r)" >/dev/null 2>&1; then PKGS="$PKGS linux-tools-common linux-tools-$(uname -r)"
      elif apt-cache show linux-tools-generic >/dev/null 2>&1; then PKGS="$PKGS linux-tools-common linux-tools-generic"
      else PKGS="$PKGS linux-perf"; fi ;;
    mongodb) PKGS="$PKGS libcurl4 openssl liblzma5 libgssapi-krb5-2 libsasl2-2 libsasl2-modules tar" ;;
    *) echo "unknown part $p" >&2; exit 2 ;;
  esac
done
SUDO=""
[ "$(id -u)" = 0 ] || SUDO=sudo
$SUDO apt-get update
# shellcheck disable=SC2086
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $PKGS
echo "installed: $PKGS"
gcc --version | head -1

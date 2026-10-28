#!/bin/sh
# Download the MongoDB server and shell the recorded MongoDB runs used (mongod 8.2.12, mongosh 2.9.1), as release
# tarballs from MongoDB, into $CLIFF_DATA/opt, and print the PATH line that puts them first.
#
#   tools/reproduce/get-mongodb.sh [MONGOD_VERSION [MONGOSH_VERSION]]     then: eval "$(tools/reproduce/get-mongodb.sh)"
#
# The server tarball is the one built for this Ubuntu release (ubuntu2404 or ubuntu2204; the recorded runs used
# ubuntu2404); on another distribution set MONGODB_DISTRO. Its libraries come from deps-ubuntu.sh mongodb.
set -eu
V=${1:-8.2.12}
SV=${2:-2.9.1}
ROOT=${CLIFF_DATA:-$HOME/.cache/cliffhunter-bugs}
DISTRO=${MONGODB_DISTRO:-}
if [ -z "$DISTRO" ]; then
  . /etc/os-release 2>/dev/null || true
  case "${ID:-}-${VERSION_ID:-}" in
    ubuntu-22.04) DISTRO=ubuntu2204 ;;
    *) DISTRO=ubuntu2404 ;;
  esac
fi
O=$ROOT/opt
mkdir -p "$O"
fetch() {  # fetch URL DIR
  [ -d "$O/$2" ] || { curl -fsSL "$1" | tar -xz -C "$O"; } >&2
}
fetch "https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-$DISTRO-$V.tgz" "mongodb-linux-x86_64-$DISTRO-$V"
fetch "https://downloads.mongodb.com/compass/mongosh-$SV-linux-x64.tgz" "mongosh-$SV-linux-x64"
B1=$O/mongodb-linux-x86_64-$DISTRO-$V/bin
B2=$O/mongosh-$SV-linux-x64/bin
if command -v ldd >/dev/null && ldd "$B1/mongod" | grep -q "not found"; then
  echo "mongod is missing libraries (run tools/reproduce/deps-ubuntu.sh mongodb):" >&2
  ldd "$B1/mongod" | grep "not found" >&2
fi
echo "export PATH=$B1:$B2:\$PATH"

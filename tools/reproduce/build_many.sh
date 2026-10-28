#!/bin/sh
# Build several commits of one system, one after another.  tools/reproduce/build_many.sh SYSTEM REV...
D=$(cd "$(dirname "$0")" && pwd)
SYS=$1; shift
for r in "$@"; do
  if out=$(sh "$D/build.sh" "$SYS" "$r" 2>&1); then echo "ok      $r -> $(echo "$out" | tail -1)"
  else echo "FAILED  $r: $(echo "$out" | tail -3 | tr '\n' ' ')"; fi
done

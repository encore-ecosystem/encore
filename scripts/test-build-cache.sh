#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
compiler=${1:-"$root/target/release/encore"}
compiler=$(cd "$(dirname "$compiler")" && pwd)/$(basename "$compiler")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/src"
cat > "$tmp/encore.toml" <<'EOF'
[project]
name = "cache_probe"
version = "0.1.0"
dependencies = []
EOF
cat > "$tmp/src/main.enq" <<'EOF'
extern fn cache_probe_value() -> u32

fn main() -> u32 {
    ret cache_probe_value()
}
EOF
cat > "$tmp/runtime.c" <<'EOF'
#include <stdint.h>
#include "value.inc"
uint32_t cache_probe_value(void) { return CACHE_PROBE_VALUE; }
EOF
printf '#define CACHE_PROBE_VALUE 7u\n' > "$tmp/value.inc"

(cd "$tmp" && "$compiler" build) > "$tmp/cold.log" 2>&1
test -f "$tmp/target/debug/.encore-fingerprint"
test -f "$tmp/target/debug/.encore-codegen-fingerprint"
test -f "$tmp/target/debug/object/native_1.o.fingerprint"

(cd "$tmp" && "$compiler" build) > "$tmp/noop.log" 2>&1
if grep -q 'Checking workspace\|cached EHIR' "$tmp/noop.log"; then
    echo "No-op build did not use the full build fingerprint" >&2
    exit 1
fi

printf '#define CACHE_PROBE_VALUE 9u\n' > "$tmp/value.inc"
(cd "$tmp" && "$compiler" build) > "$tmp/native.log" 2>&1
grep -q 'cached EHIR, LLVM IR and object' "$tmp/native.log"
grep -q '1 of 3 objects' "$tmp/native.log"
set +e
"$tmp/target/debug/cache_probe"
status=$?
set -e
if [[ $status -ne 9 ]]; then
    echo "Native include change was not reflected in the binary" >&2
    exit 1
fi

sed -i 's/ret cache_probe_value()/let value = cache_probe_value()\n    ret value/' "$tmp/src/main.enq"
(cd "$tmp" && "$compiler" build) > "$tmp/source.log" 2>&1
grep -q 'EHIR generated' "$tmp/source.log"
if grep -q 'cached EHIR' "$tmp/source.log"; then
    echo "Encore source change incorrectly reused codegen" >&2
    exit 1
fi

echo "Build cache invalidation tests passed"

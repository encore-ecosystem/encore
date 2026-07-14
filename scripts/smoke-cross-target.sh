#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: smoke-cross-target.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

cp -R "$repo_root/examples/add_two_structs" "$tmp/project"
rm -rf "$tmp/project/target"
(
    cd "$tmp/project"
    "$compiler" build \
        --profile debug \
        --target thumbv7em-none-eabihf \
        --target-cpu cortex-m4 \
        --emit object
)

object="$tmp/project/target/thumbv7em-none-eabihf/debug/object/add_two_structs.o"
test -s "$object"
file "$object" | grep -q "ELF 32-bit.*ARM"

set +e
output=$(
    cd "$tmp/project"
    "$compiler" build \
        --profile debug \
        --target thumbv7em-none-eabihf \
        --target-cpu cortex-m4 \
        --emit binary 2>&1
)
code=$?
set -e
test "$code" -ne 0
printf '%s\n' "$output" | grep -q "binary output requires builtin-runtime or target.runtime-sources"

cp -R "$repo_root/examples/bare_metal" "$tmp/bare-metal"
rm -rf "$tmp/bare-metal/target"
(
    cd "$tmp/bare-metal"
    "$compiler" build --profile debug --emit binary
)
firmware="$tmp/bare-metal/target/thumbv7em-none-eabi/debug/bare_metal"
test -s "$firmware"
file "$firmware" | grep -q "ELF 32-bit.*ARM"
entry=$(readelf -h "$firmware" | awk '/Entry point address:/ { print $4 }')
test -n "$entry"
test "$entry" != "0x0"
if command -v llvm-nm >/dev/null 2>&1; then
    test -z "$(llvm-nm --undefined-only "$firmware")"
fi

cp -R "$repo_root/examples/add_two_structs" "$tmp/custom-runtime"
rm -rf "$tmp/custom-runtime/target"
printf '\n[target]\nbuiltin-runtime = false\n' >> "$tmp/custom-runtime/encore.toml"
set +e
output=$(
    cd "$tmp/custom-runtime"
    "$compiler" build --profile debug 2>&1
)
code=$?
set -e
test "$code" -ne 0
printf '%s\n' "$output" | grep -q "binary output requires builtin-runtime or target.runtime-sources"

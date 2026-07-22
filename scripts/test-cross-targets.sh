#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler=${ENCORE_BIN:-$repo_root/target/debug/encore}
example=$repo_root/examples/bare_metal
target=thumbv7em-none-eabi

"$compiler" target show "$target" | grep -q "Target:        $target"
(
    cd "$example"
    "$compiler" build --profile debug --emit object
    "$compiler" build --profile debug --emit binary
)

object=$example/target/$target/debug/object/bare_metal.o
binary=$example/target/$target/debug/bare_metal
test -s "$object"
test -s "$binary"
file "$binary" | grep -q 'ELF 32-bit LSB executable, ARM, EABI5'

error_output=$example/target/missing-linker-script.output
if (cd "$example" && "$compiler" build --profile debug --emit binary --linker-script platform/missing.ld >"$error_output" 2>&1); then
    echo "cross-target build unexpectedly accepted a missing linker script" >&2
    exit 1
fi
grep -q 'target linker script does not exist: platform/missing.ld' "$error_output"
rm -f "$error_output"

invalid_driver=$repo_root/scripts/fixtures/targets/invalid-driver
driver_output=$invalid_driver/target/invalid-driver.output
mkdir -p "$invalid_driver/target"
if (cd "$invalid_driver" && "$compiler" build --emit object >"$driver_output" 2>&1); then
    echo "cross-target build unexpectedly accepted an unsupported toolchain driver" >&2
    exit 1
fi
grep -q "unsupported target toolchain driver 'gcc'; supported drivers: clang" "$driver_output"
rm -f "$driver_output"

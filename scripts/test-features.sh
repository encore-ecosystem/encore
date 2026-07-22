#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler=${ENCORE_BIN:-$repo_root/target/debug/encore}
fixture=$repo_root/scripts/fixtures/features

(cd "$fixture" && "$compiler" sync && "$compiler" build --profile debug)
"$fixture/target/debug/feature_union_fixture"

grep -q 'features = \["left"' "$fixture/encore.lock"
grep -q '"right"' "$fixture/encore.lock"

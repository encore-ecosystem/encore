#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: test-ci-local.sh <seed-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
seed=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1")
cd "$repo_root"

export ENCORE_CORE_DIR="$repo_root/index/core"

"$seed" --version
"$seed" build --profile extreme
mkdir -p target/stage1
cp target/extreme/encore target/stage1/encore
rm -rf target/stage1-extreme
mv target/extreme target/stage1-extreme

stage1="$repo_root/target/stage1/encore"
"$stage1" --version
"$stage1" build --profile extreme
mkdir -p target/stage2
cp target/extreme/encore target/stage2/encore
rm -rf target/stage2-extreme
mv target/extreme target/stage2-extreme

stage2="$repo_root/target/stage2/encore"
"$stage2" --version
"$stage2" build --profile extreme
mkdir -p target/stage3
cp target/extreme/encore target/stage3/encore

stage3="$repo_root/target/stage3/encore"
"$stage3" --version
cmp "$stage2" "$stage3"
compiler="$stage3"

for package in \
    index/core \
    index/color \
    index/colorterm \
    index/dict \
    index/ehir \
    index/ehir-llvm-backend \
    index/encore-ui \
    index/geometry \
    index/json \
    index/llvm \
    index/log \
    index/lsp \
    index/rich \
    index/std \
    index/toml \
    .
do
    (cd "$package" && "$compiler" test)
done

scripts/test-analyzer.sh "$compiler"
scripts/test-tooling-foundation.sh "$compiler"
scripts/test-complete-analysis.sh "$compiler"
scripts/test-lsp-integration.sh "$compiler"
scripts/test-cli-contract.sh "$compiler"
scripts/test-release-channels.sh
scripts/test-self-update.sh "$compiler"
ENCORE_BIN="$compiler" scripts/test-cross-targets.sh
scripts/test-memory-safety.sh "$compiler"
scripts/test-https-stack.sh "$compiler"

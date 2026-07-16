#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

if [ "$#" -gt 1 ]; then
    echo "usage: verify-bootstrap.sh [stage0-compiler]" >&2
    exit 2
fi

if [ "$#" -eq 1 ]; then
    stage0_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
    cp "$stage0_dir/$(basename -- "$1")" "$tmp/stage0"
else
    gzip -dc "$repo_root/bootstrap/encore-stage0-linux-x86_64.gz" > "$tmp/stage0"
fi
chmod +x "$tmp/stage0"

target=x86_64-unknown-linux-gnu
runtime_sources="$repo_root/index/core/runtime.c $repo_root/index/ehir-llvm-backend/runtime.c $repo_root/index/rich/runtime.c"

stage=1
while [ "$stage" -le 3 ]; do
    previous=$((stage - 1))
    (
        cd "$repo_root"
        ENCORE_CORE_DIR="$repo_root/index/core" "$tmp/stage$previous" \
            build --profile debug --target "$target" --emit llvm-ir
    )
    cp "$repo_root/target/$target/debug/encore.ll" "$tmp/stage$stage.ll"
    if [ "$stage" -lt 3 ]; then
        # shellcheck disable=SC2086
        clang -O0 -w "$tmp/stage$stage.ll" $runtime_sources -o "$tmp/stage$stage"
    fi
    stage=$((stage + 1))
done

if ! cmp -s "$tmp/stage2.ll" "$tmp/stage3.ll"; then
    echo "Bootstrap did not converge: stage2 LLVM IR differs from stage3" >&2
    sha256sum "$tmp/stage2.ll" "$tmp/stage3.ll" >&2
    exit 1
fi

hash=$(sha256sum "$tmp/stage2.ll" | awk '{print $1}')
printf 'Bootstrap converged at stage2: %s\n' "$hash"

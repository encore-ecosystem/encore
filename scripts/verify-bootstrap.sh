#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
profile_dir=""
cleanup() {
    if [ -n "$profile_dir" ] && [ ! -e "$profile_dir" ]; then
        if [ -d "$tmp/original-profile" ]; then
            mv "$tmp/original-profile" "$profile_dir"
        elif [ -d "$tmp/stage3-profile" ]; then
            mv "$tmp/stage3-profile" "$profile_dir"
        fi
    fi
    rm -rf "$tmp"
}
trap cleanup EXIT HUP INT TERM

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
profile=${ENCORE_BOOTSTRAP_PROFILE:-extreme}
profile_dir="$repo_root/target/$target/$profile"
runtime_sources="$repo_root/runtime.c $repo_root/index/core/runtime.c $repo_root/index/ehir-llvm-backend/runtime.c $repo_root/index/rich/runtime.c"
if [ -d "$profile_dir" ]; then mv "$profile_dir" "$tmp/original-profile"; fi

stage=1
while [ "$stage" -le 3 ]; do
    previous=$((stage - 1))
    (
        cd "$repo_root"
        ENCORE_CORE_DIR="$repo_root/index/core" "$tmp/stage$previous" \
            build --profile "$profile" --target "$target" --emit llvm-ir
    )
    cp "$profile_dir/encore.ll" "$tmp/stage$stage.ll"
    mv "$profile_dir" "$tmp/stage$stage-profile"
    if [ "$stage" -lt 3 ]; then
        # shellcheck disable=SC2086
        clang -O3 -w "$tmp/stage$stage.ll" $runtime_sources -lssl -lcrypto -o "$tmp/stage$stage"
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

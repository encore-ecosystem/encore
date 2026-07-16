#!/usr/bin/env sh
set -eu

allow_dirty=false
if [ "${1:-}" = "--allow-dirty" ]; then
    allow_dirty=true
    shift
fi
if [ "$#" -ne 1 ]; then
    echo "usage: update-stage0.sh [--allow-dirty] <native-encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
source_dirty=false
if [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no)" ]; then
    source_dirty=true
fi
if [ "$source_dirty" = true ] && [ "$allow_dirty" != true ]; then
    echo "Refusing to update stage0 from a dirty tracked worktree" >&2
    exit 1
fi

version_output=$($compiler --version)
case "$version_output" in
    "encore "*) version=${version_output#encore } ;;
    *) echo "Unable to read compiler version from: $version_output" >&2; exit 1 ;;
esac
source_commit=$(git -C "$repo_root" rev-parse HEAD)
target=x86_64-unknown-linux-gnu
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

(
    cd "$repo_root"
    "$compiler" build --profile extreme --target "$target" --emit llvm-ir
)
clang -O3 \
    "$repo_root/target/$target/extreme/encore.ll" \
    "$repo_root/index/core/runtime.c" \
    "$repo_root/index/ehir-llvm-backend/runtime.c" \
    "$repo_root/index/rich/runtime.c" \
    -o "$tmp/encore-stage0-linux-x86_64"
gzip -9n -c "$tmp/encore-stage0-linux-x86_64" > "$tmp/encore-stage0-linux-x86_64.gz"

sha256sum "$tmp/encore-stage0-linux-x86_64.gz" | sed 's#  .*/#  bootstrap/#' > "$tmp/archive.sha256"
sha256sum "$tmp/encore-stage0-linux-x86_64" | sed 's#  .*/#  #' > "$tmp/binary.sha256"
{
    printf 'version=%s\n' "$version"
    printf 'source_commit=%s\n' "$source_commit"
    printf 'source_dirty=%s\n' "$source_dirty"
    printf 'build_target=%s\n' "$target"
    printf 'build_system=%s\n' "$(uname -s) $(uname -r) $(uname -m)"
} > "$tmp/provenance"

mv "$tmp/encore-stage0-linux-x86_64.gz" "$repo_root/bootstrap/encore-stage0-linux-x86_64.gz"
mv "$tmp/archive.sha256" "$repo_root/bootstrap/encore-stage0-linux-x86_64.sha256"
mv "$tmp/binary.sha256" "$repo_root/bootstrap/encore-stage0-linux-x86_64.binary.sha256"
mv "$tmp/provenance" "$repo_root/bootstrap/encore-stage0-linux-x86_64.provenance"
"$repo_root/scripts/verify-stage0.sh"

#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 ]]; then
  echo 'usage: ci-produce-stage1.sh SEED_COMPILER SEED_TAG WINDOWS_GNU_TARGET' >&2
  exit 2
fi
seed_compiler=$1
seed_tag=$2
target=$3
case "$target" in
  x86_64-w64-windows-gnu|aarch64-w64-windows-gnu) ;;
  *) echo "Unsupported Windows GNU target: $target" >&2; exit 2 ;;
esac
: "${LLVM_MINGW_ROOT:?LLVM_MINGW_ROOT is required for Windows GNU stage1}"

release=$(tr -d '\r\n' < VERSION)
version=${release%%-*}
release_name=${release#*-}
test "$release" = "$version-$release_name"
target_kit_abi=$(printf '%s\n' "$version" | awk -F. '{print $1 "." $2}')
test -f packages/core/encore.toml
export ENCORE_CORE_DIR="$PWD/packages/core"

mkdir -p target/stage1-builder
"$seed_compiler" build --profile extreme
cp target/extreme/encore target/stage1-builder/encore
builder="$PWD/target/stage1-builder/encore"
chmod +x "$builder"
ENCORE_CC="$LLVM_MINGW_ROOT/bin/clang" \
ENCORE_LINKER="$LLVM_MINGW_ROOT/bin/clang" \
ENCORE_AR="$LLVM_MINGW_ROOT/bin/llvm-ar" \
  "$builder" build --profile extreme --target "$target"

source="target/$target/extreme/encore.exe"
test -s "$source"
destination="target/stage1-artifacts/$target"
mkdir -p "$destination"
cp "$source" "$destination/encore.exe"
executable_checksum=$(sha256sum "$destination/encore.exe" | awk '{print $1}')
jq -n --arg commit "${GITHUB_SHA:?}" --arg version "$version" \
  --arg nametag "$release_name" --arg release "$release" --arg seed "$seed_tag" \
  --arg target "$target" --arg target_kit_abi "$target_kit_abi" \
  --arg sha256 "$executable_checksum" \
  '{schema:3, commit:$commit, version:$version, nametag:$nametag,
    release:$release, seed:$seed, bootstrap:null, producer:"linux", target:$target,
    target_kit_abi:$target_kit_abi,
    executable:"encore.exe", executable_sha256:$sha256}' > "$destination/manifest.json"

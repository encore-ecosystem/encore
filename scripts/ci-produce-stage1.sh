#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: ci-produce-stage1.sh SEED_COMPILER PRODUCER SEED_TAG TARGET..." >&2
  exit 2
fi

seed_compiler=$1
producer=$2
seed_tag=$3
shift 3
targets=("$@")

case "$producer" in
  linux|darwin) executable=encore ;;
  windows) executable=encore.exe ;;
  *) echo "unknown producer: $producer" >&2; exit 2 ;;
esac

version=$(tr -d '\r\n' < VERSION)
target_kit_abi=$(printf '%s\n' "$version" | awk -F. '{print $1 "." $2}')
dependencies_checksum=$(awk 'NF {print tolower($1); exit}' \
  target/dependency-download/dependencies.tar.gz.sha256)
mkdir -p target/stage1-builder target/stage1-artifacts

"$seed_compiler" build --profile extreme
cp "target/extreme/$executable" "target/stage1-builder/$executable"
builder="$PWD/target/stage1-builder/$executable"
chmod +x "$builder" 2>/dev/null || true

# The seed can only parse the pre-edge core used for the bridge build. Restore
# the exact pinned release core before stage1 compiles any release artifact.
: "${ENCORE_RELEASE_CORE_DIR:?ENCORE_RELEASE_CORE_DIR is required}"
index_root="$PWD/../encore-index"
rm -rf "$index_root/packages/core"
cp -R "$ENCORE_RELEASE_CORE_DIR" "$index_root/packages/core"
export ENCORE_CORE_DIR="$index_root/packages/core"

for target in "${targets[@]}"; do
  target_executable=encore
  [[ "$target" == *-windows-* ]] && target_executable=encore.exe
  args=(build --profile extreme --target "$target")

  case "$target" in
    aarch64-unknown-linux-gnu)
      : "${LLVM_MINGW_ROOT:?LLVM_MINGW_ROOT is required for Linux AArch64 stage1}"
      args+=(--cc "$LLVM_MINGW_ROOT/bin/clang"
        --linker "$LLVM_MINGW_ROOT/bin/clang"
        --ar "$LLVM_MINGW_ROOT/bin/llvm-ar"
        --sysroot "$LLVM_MINGW_ROOT/linux-aarch64-sysroot"
        --link-arg "-fuse-ld=lld")
      ;;
    x86_64-w64-windows-gnu|aarch64-w64-windows-gnu)
      : "${LLVM_MINGW_ROOT:?LLVM_MINGW_ROOT is required for Windows GNU stage1}"
      args+=(--cc "$LLVM_MINGW_ROOT/bin/clang"
        --linker "$LLVM_MINGW_ROOT/bin/clang"
        --ar "$LLVM_MINGW_ROOT/bin/llvm-ar")
      ;;
  esac

  "$builder" "${args[@]}"
  source="target/$target/extreme/$target_executable"
  if [[ "$target" == "$(uname -m)-unknown-linux-gnu" && "$producer" == linux ]]; then
    source="target/$target/extreme/$target_executable"
  elif [[ "$target" == aarch64-apple-darwin && "$producer" == darwin ]]; then
    source="target/$target/extreme/$target_executable"
  elif [[ "$target" == x86_64-pc-windows-msvc && "$producer" == windows ]]; then
    source="target/$target/extreme/$target_executable"
  fi
  test -s "$source"

  destination="target/stage1-artifacts/$target"
  mkdir -p "$destination"
  cp "$source" "$destination/$target_executable"
  chmod +x "$destination/$target_executable" 2>/dev/null || true
  if command -v sha256sum >/dev/null 2>&1; then
    executable_checksum=$(sha256sum "$destination/$target_executable" | awk '{print $1}')
  else
    executable_checksum=$(shasum -a 256 "$destination/$target_executable" | awk '{print $1}')
  fi
  jq -n \
    --arg commit "$GITHUB_SHA" \
    --arg version "$version" \
    --arg seed "$seed_tag" \
    --arg producer "$producer" \
    --arg target "$target" \
    --arg target_kit_abi "$target_kit_abi" \
    --arg dependencies "$dependencies_checksum" \
    --arg executable "$target_executable" \
    --arg sha256 "$executable_checksum" \
    '{
      schema: 1,
      commit: $commit,
      version: $version,
      seed: $seed,
      producer: $producer,
      target: $target,
      target_kit_abi: $target_kit_abi,
      dependencies_sha256: $dependencies,
      executable: $executable,
      executable_sha256: $sha256
    }' > "$destination/manifest.json"
done

#!/usr/bin/env bash
set -euo pipefail

# Native builds stay on one runner. A bridge provides only GNU stage1.
triple=${CI_TARGET:?}
executable=${CI_EXECUTABLE:?}
seed_tag=${CI_SEED_TAG:?}
stage1=${1:-}
bootstrap=null
build_args=(build --profile extreme)
if [[ -n "${CI_BUILD_JOBS:-}" ]]; then
  build_args+=(--jobs "$CI_BUILD_JOBS")
fi
hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}
if [[ -n "$stage1" ]]; then
  bootstrap=$(jq '.bootstrap' "${STAGE1_MANIFEST:?}")
else
  seed=${SEED_COMPILER:?}
  test ! -e target/extreme
  test ! -e target/bootstrap-cache-1
  ENCORE_BUILD_CACHE="$PWD/target/bootstrap-cache-1" \
    bash "$(dirname "$0")/ci-seed-build.sh" "$seed" "$seed_tag" "${build_args[@]}"
  mkdir -p target/stage1
  cp "target/extreme/$executable" "target/stage1/$executable"
  mv target/extreme target/stage1-output
  stage1="$PWD/target/stage1/$executable"
fi
chmod +x "$stage1" 2>/dev/null || true

# Neither the output nor compiled-package caches are shared across stages.
# This also prevents a converged stage from passing by hydrating its own binary.
test ! -e target/extreme
test ! -e target/bootstrap-cache-2
ENCORE_BUILD_CACHE="$PWD/target/bootstrap-cache-2" "$stage1" "${build_args[@]}"
mkdir -p target/stage2
cp "target/extreme/$executable" "target/stage2/$executable"
mv target/extreme target/stage2-output
test ! -e target/bootstrap-cache-3
ENCORE_BUILD_CACHE="$PWD/target/bootstrap-cache-3" "$PWD/target/stage2/$executable" "${build_args[@]}"
mkdir -p target/stage3
cp "target/extreme/$executable" "target/stage3/$executable"
cmp "target/stage2/$executable" "target/stage3/$executable"
stage2_sha=$(hash_file "target/stage2/$executable")
stage3_sha=$(hash_file "target/stage3/$executable")
release=$(tr -d '\r\n' < VERSION)
version=${release%%-*}
nametag=${release#*-}
test "$("$PWD/target/stage3/$executable" --version)" = "encore $release"
jq -n --arg commit "${GITHUB_SHA:?}" --arg release "$release" --arg version "$version" \
  --arg nametag "$nametag" --arg target "$triple" --arg seed "$seed_tag" \
  --arg stage2 "$stage2_sha" --arg stage3 "$stage3_sha" --argjson bootstrap "$bootstrap" \
  '{schema:3, commit:$commit, release:$release, version:$version, nametag:$nametag,
    target:$target, seed:$seed,
    compiler_sha256:$stage3, stage2_sha256:$stage2, stage3_sha256:$stage3,
    converged:true, bootstrap:$bootstrap}' > target/convergence.json

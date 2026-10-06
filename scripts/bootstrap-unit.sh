#!/usr/bin/env bash
# Rebuild the published 0.1.0 source with the minimal unit-payload backport.
# This is a build tool, never an installed or published replacement release.
set -euo pipefail
if [[ $# != 2 ]]; then
  echo "usage: bootstrap-unit.sh SEED_COMPILER OUTPUT_DIRECTORY" >&2
  exit 2
fi
seed=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
test "$("$seed" --version)" = 'encore 0.1.0-neumann'
repository=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$2"
output=$(cd "$2" && pwd)
work=$(mktemp -d "$output/source.XXXXXX")
compiler_commit=6f4147c28239694e6c2bf0fb6f4f2f75ce6eb27f
index_commit=ba182e7adef7fd08089b7b5b8126235eac5606e7
executable=encore
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) executable=encore.exe ;; esac

fetch_source() {
  local name=$1 commit=$2
  git init --quiet "$work/$name"
  git -C "$work/$name" config core.autocrlf false
  git -C "$work/$name" fetch --quiet --depth 1 \
    "https://github.com/encore-ecosystem/$name.git" "$commit"
  git -C "$work/$name" checkout --quiet --detach FETCH_HEAD
  test "$(git -C "$work/$name" rev-parse HEAD)" = "$commit"
}
fetch_source encore "$compiler_commit"
fetch_source encore-index "$index_commit"
# A separate root keeps git apply independent of the invoking checkout.
git init --quiet "$work"
git -C "$work" apply --check "$repository/scripts/bootstrap-unit.patch"
git -C "$work" apply "$repository/scripts/bootstrap-unit.patch"
(
  cd "$work/encore"
  ENCORE_CORE_DIR="$work/encore-index/packages/core" \
    "$seed" build --profile extreme --jobs "${ENCORE_BOOTSTRAP_JOBS:-2}"
)
mkdir -p "$output/bin" "$work/probe/src"
cp "$work/encore/target/extreme/$executable" "$output/bin/$executable"
chmod +x "$output/bin/$executable" 2>/dev/null || true
printf '[project]\nname = "unit_probe"\nversion = "0.0.0"\ndependencies = ["sys@core"]\n' \
  > "$work/probe/encore.toml"
cp "$repository/tests/result_unit_payload.enq" "$work/probe/src/main.enq"
(
  cd "$work/probe"
  ENCORE_CORE_DIR="$work/encore-index/packages/core" \
    "$output/bin/$executable" run --jobs 1
)
hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}
jq -n --arg compiler "$compiler_commit" --arg index "$index_commit" \
  --arg patch "$(hash_file "$repository/scripts/bootstrap-unit.patch")" \
  --arg seed "$(hash_file "$seed")" --arg binary "$(hash_file "$output/bin/$executable")" \
  '{kind:"unit-payload-backport",compiler_commit:$compiler,index_commit:$index,
    patch_sha256:$patch,seed_sha256:$seed,compiler_sha256:$binary}' > "$output/provenance.json"

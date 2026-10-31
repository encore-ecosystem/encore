#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == --version ]]; then echo "encore ${CI_PROBE_RELEASE:-0.1.4-neumann}"; exit 0; fi
test "$1" = build
test "$2" = --profile
test "$3" = extreme
if [[ -n "${CI_BUILD_JOBS:-}" ]]; then
  test "$4" = --jobs && test "$5" = "$CI_BUILD_JOBS"
fi
case "$CI_PROBE_CASE" in
  seed-compat)
    test "$(cat packages/json/src/lib.enq)" = seed-json
    test "$(cat src/frontend/analysis_database.enq)" = configured-analysis
    test "$(cat src/modes/build.enq)" = seed-build
    test "$(cat src/target/mod.enq)" = current-target
    test ! -e packages/core/src/reflect/mod.enq
    mkdir -p target/extreme
    cp "$0" target/extreme/encore
    exit 0
    ;;
esac
test ! -e "$ENCORE_BUILD_CACHE"
test ! -e target/extreme
mkdir -p "$ENCORE_BUILD_CACHE" target/extreme
phase=$(basename "$(dirname "$0")")
printf '%s\n' "$phase" >> phases
if [[ "$CI_PROBE_CASE" == build-failure && "$phase" == stage1 ]]; then exit 17; fi
executable=${CI_EXECUTABLE:-encore}
cp "$0" "target/extreme/$executable"
if [[ "$CI_PROBE_CASE" == mismatch && "$phase" == stage2 ]]; then
  printf '\n# mismatched stage3\n' >> "target/extreme/$executable"
fi
chmod +x "target/extreme/$executable"

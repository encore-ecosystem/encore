#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == --version ]]; then echo 'encore 0.1.4-neumann'; exit 0; fi
test "$1" = build
test "$2" = --profile
test "$3" = extreme
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
  bridge-x86|bridge-arm)
    if [[ $# == 3 ]]; then
      mkdir -p target/extreme
      cp "$0" target/extreme/encore
      printf 'producer\n' >> phases
    else
      test $# == 5 && test "$4" = --target && test "$5" = "$CI_PROBE_TARGET"
      test "$ENCORE_CC" = "$LLVM_MINGW_ROOT/bin/clang"
      test "$ENCORE_LINKER" = "$LLVM_MINGW_ROOT/bin/clang"
      test "$ENCORE_AR" = "$LLVM_MINGW_ROOT/bin/llvm-ar"
      mkdir -p "target/$5/extreme"
      cp "$0" "target/$5/extreme/encore.exe"
      printf 'cross\n' >> phases
    fi
    exit 0
    ;;
esac
test ! -e "$ENCORE_BUILD_CACHE"
test ! -e target/extreme
mkdir -p "$ENCORE_BUILD_CACHE" target/extreme
phase=$(basename "$(dirname "$0")")
printf '%s\n' "$phase" >> phases
if [[ "$CI_PROBE_CASE" == build-failure && "$phase" == stage1 ]]; then exit 17; fi
cp "$0" target/extreme/encore
if [[ "$CI_PROBE_CASE" == mismatch && "$phase" == stage2 ]]; then
  printf '\n# mismatched stage3\n' >> target/extreme/encore
fi
chmod +x target/extreme/encore

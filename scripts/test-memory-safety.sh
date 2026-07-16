#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-memory-safety.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

for test_name in \
    owned_expression_statement \
    string_match_literal_lifetime \
    string_compound_assignment_lifetime \
    lexer_tracks_token_positions \
    lexer_lifetime \
    parser_lifetime \
    owned_aggregate_return \
    owned_shadowing_lifetime \
    owned_reassignment_lifetime \
    temporary_mutable_receiver_lifetime \
    ehir_parser_lifetime \
    heap_path_lifetime \
    vec_owned_cow_lifetime \
    translator_lifetime \
    for_early_return_lifetime
do
    (
        cd "$repo_root"
        ENCORE_KEEP_TEMPS=1 "$compiler" test --filter "$test_name"
    )
    llvm_path=$(find "$repo_root/target/tests" -maxdepth 1 -name "*${test_name}*.ll" -print -quit)
    if [ -z "$llvm_path" ]; then
        echo "missing LLVM IR for memory test: $test_name" >&2
        exit 1
    fi
    clang -O0 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
        -Wno-override-module "$llvm_path" "$repo_root/index/core/runtime.c" \
        -o "$tmp/$test_name"
    ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
        UBSAN_OPTIONS=halt_on_error=1 \
        "$tmp/$test_name"
done

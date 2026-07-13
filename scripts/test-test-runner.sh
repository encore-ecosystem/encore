#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-test-runner.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
cleanup() {
    code=$1
    trap - 0
    if [ "$code" -ne 0 ]; then
        for log in "$tmp"/*.log; do
            if [ -f "$log" ]; then
                printf '\n--- %s ---\n' "$(basename -- "$log")" >&2
                cat "$log" >&2
            fi
        done
    fi
    rm -rf "$tmp"
    exit "$code"
}
trap 'cleanup $?' 0
trap 'exit 1' HUP INT TERM
cp -R "$repo_root/scripts/fixtures/test-runner" "$tmp/project"

run_test() {
    output_file=$1
    shift
    (cd "$tmp/project" && "$compiler" test "$@") >"$output_file" 2>&1
}

run_test "$tmp/passing.log" --filter passing_unit
grep -q "1 passed; 0 failed" "$tmp/passing.log"
grep -q "test test_runner_fixture:src/main.enq::passing_unit ... ok (" "$tmp/passing.log"
if grep -q "$tmp/project" "$tmp/passing.log"; then
    echo "Test output contains an absolute project path" >&2
    exit 1
fi

run_test "$tmp/expected.log" --filter expected_diagnostic
grep -q "1 passed; 0 failed" "$tmp/expected.log"

set +e
run_test "$tmp/wrong.log" --filter wrong_diagnostic
wrong_code=$?
set -e
test "$wrong_code" -ne 0
grep -q "expected compile error containing 'This diagnostic must not match'" "$tmp/wrong.log"
grep -q "0 passed; 1 failed" "$tmp/wrong.log"
grep -q "failures:" "$tmp/wrong.log"
grep -q "    test_runner_fixture:tests/wrong_diagnostic.enq" "$tmp/wrong.log"

set +e
run_test "$tmp/signature.log" --filter invalid_signature
signature_code=$?
set -e
test "$signature_code" -ne 0
grep -q "test must be fn() -> bool" "$tmp/signature.log"

run_test "$tmp/empty.log" --filter no_such_test
grep -q "No tests found." "$tmp/empty.log"

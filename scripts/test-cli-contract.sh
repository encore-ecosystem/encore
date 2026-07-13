#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-cli-contract.sh <encore-compiler>" >&2
    exit 2
fi

compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

(cd "$tmp" && "$compiler") > "$tmp/global.log" 2>&1
grep -q "Usage: encore <command> \[options\]" "$tmp/global.log"
(cd "$tmp" && "$compiler" --help) > "$tmp/help.log" 2>&1
cmp "$tmp/global.log" "$tmp/help.log"
(cd "$tmp" && "$compiler" -h) > /dev/null
(cd "$tmp" && "$compiler" -V) | grep -Eq '^encore [0-9]+\.[0-9]+\.[0-9]+$'

for command in build run test init add sync update install target; do
    (cd "$tmp" && "$compiler" "$command" --help) > "$tmp/$command.log" 2>&1
    grep -q "Usage: encore $command" "$tmp/$command.log"
    (cd "$tmp" && "$compiler" help "$command") > "$tmp/$command-help.log" 2>&1
    cmp "$tmp/$command.log" "$tmp/$command-help.log"
done

set +e
(cd "$tmp" && "$compiler" unknown-command) > "$tmp/unknown.log" 2>&1
code=$?
set -e
test "$code" -ne 0
grep -q "Unknown command: unknown-command" "$tmp/unknown.log"
grep -q "encore --help" "$tmp/unknown.log"

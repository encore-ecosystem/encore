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

for invocation in "build --unknown" "build --target" "test --filter" "init extra" "add" "sync extra" "update extra" "install one two" "target one two"; do
    set +e
    (cd "$tmp" && "$compiler" $invocation) > "$tmp/invalid.log" 2>&1
    invalid_code=$?
    set -e
    test "$invalid_code" -eq 2
    grep -q "Error:" "$tmp/invalid.log"
    grep -q -- "--help' for usage" "$tmp/invalid.log"
done

# Everything after the separator belongs to the compiled program. Validation
# must reach project loading instead of rejecting these arguments.
set +e
(cd "$tmp" && "$compiler" run -- --unknown-program-flag) > "$tmp/run-args.log" 2>&1
run_code=$?
set -e
test "$run_code" -ne 2
grep -q "encore.toml" "$tmp/run-args.log"

set +e
(cd "$tmp" && "$compiler" target fictional-unknown-none) > "$tmp/target.log" 2>&1
target_code=$?
set -e
test "$target_code" -eq 1
grep -q "unsupported target architecture 'fictional'" "$tmp/target.log"

mkdir -p "$tmp/dependency/src" "$tmp/project/src"
cat > "$tmp/dependency/encore.toml" <<'EOF'
[project]
name = "fixture_dependency"
version = "1.2.3"
dependencies = []
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/dependency/src/main.enq"
cat > "$tmp/project/encore.toml" <<'EOF'
[project]
name = "fixture_project"
version = "0.0.0"
dependencies = ["path@../dependency"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/project/src/main.enq"
(cd "$tmp/project" && "$compiler" sync) > "$tmp/sync.log"
grep -q '^version = 1$' "$tmp/project/encore.lock"
grep -q '^name = "fixture_dependency"$' "$tmp/project/encore.lock"
grep -q '^ref = "path@../dependency"$' "$tmp/project/encore.lock"
grep -q '^version = "1.2.3"$' "$tmp/project/encore.lock"
grep -q '^ref = "sys@core"$' "$tmp/project/encore.lock"
if grep -Fq "$tmp" "$tmp/project/encore.lock"; then
    echo "encore.lock contains a machine-specific absolute path" >&2
    exit 1
fi

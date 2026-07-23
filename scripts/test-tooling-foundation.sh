#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-tooling-foundation.sh <encore-compiler>" >&2
    exit 2
fi

compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

file_hash() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

mkdir -p "$tmp/project/src"
cat > "$tmp/project/encore.toml" <<'EOF'
[project]
name = "tooling_fixture"
version = "0.0.0"
dependencies = []
EOF
cat > "$tmp/project/src/main.enq" <<'EOF'
//! Exercises the shared tooling foundation.

/// Adds two values.
pub fn add(lhs:u32,rhs: u32)->u32{ret lhs+rhs}

fn main()->u32{
	let value:u32=add(1_u32,2_u32)    
	if value!=3_u32{ret 1_u32}
	ret 0_u32
}
EOF

# The public CLI exposes separate check, lint, and format commands.
"$compiler" check --help > "$tmp/check-help.log"
"$compiler" lint --help > "$tmp/lint-help.log"
"$compiler" format --help > "$tmp/format-help.log"
grep -q 'Usage: encore check \[options\] \[path\]' "$tmp/check-help.log"
grep -q 'Usage: encore lint \[options\] \[path\]' "$tmp/lint-help.log"
grep -q 'Usage: encore format \[options\] \[path\]' "$tmp/format-help.log"
grep -q -- '--check' "$tmp/format-help.log"
grep -q -- '--fix' "$tmp/lint-help.log"

# Check performs complete semantic analysis without generating build artifacts.
(cd "$tmp/project" && "$compiler" check) > "$tmp/check.log" 2>&1
grep -q 'Checked 1 module' "$tmp/check.log"
test ! -e "$tmp/project/target"

cp "$tmp/project/src/main.enq" "$tmp/valid.enq"
cat > "$tmp/project/src/main.enq" <<'EOF'
fn value() -> u32 { ret 42_u32 }
fn main() -> u32 { let answer: str = value() ret 0_u32 }
EOF
set +e
(cd "$tmp/project" && "$compiler" check --format json) > "$tmp/check-invalid.log" 2>&1
check_invalid_code=$?
set -e
test "$check_invalid_code" -eq 1
grep -q '"code":"type-mismatch"' "$tmp/check-invalid.log"
grep -q '"path":".*src/main.enq"' "$tmp/check-invalid.log"
grep -q '"severity":"error"' "$tmp/check-invalid.log"
test ! -e "$tmp/project/target"

cat > "$tmp/project/src/main.enq" <<'EOF'
fn duplicate() -> u32 { ret 1_u32 }
fn duplicate() -> u32 { ret 2_u32 }
fn main() -> u32 { ret duplicate() }
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/check-shared-semantics.log" 2>&1
shared_semantics_code=$?
set -e
test "$shared_semantics_code" -eq 1
grep -q 'error\[duplicate-function\]' "$tmp/check-shared-semantics.log"

cat > "$tmp/project/src/main.enq" <<'EOF'
fn value(input: u32) -> u32 { ret input }
fn main() -> u32 { ret value(1_u32, 2_u32) }
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/check-arity.log" 2>&1
arity_code=$?
set -e
test "$arity_code" -eq 1
grep -q 'error\[argument-mismatch\]' "$tmp/check-arity.log"

cat > "$tmp/project/src/main.enq" <<'EOF'
fn main() -> str { ret 0_u32 }
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/check-return.log" 2>&1
return_code=$?
set -e
test "$return_code" -eq 1
grep -q 'error\[return-type-mismatch\]' "$tmp/check-return.log"
mv "$tmp/valid.enq" "$tmp/project/src/main.enq"

# Lint reuses the shared database, supports configurable severities, and can
# apply safe fixes without changing program behavior.
set +e
(cd "$tmp/project" && "$compiler" lint --deny trailing-whitespace) > "$tmp/lint.log" 2>&1
lint_code=$?
set -e
test "$lint_code" -eq 1
grep -q 'error\[trailing-whitespace\]' "$tmp/lint.log"
(cd "$tmp/project" && "$compiler" lint --fix --deny trailing-whitespace) > "$tmp/lint-fix.log" 2>&1
grep -q 'Fixed 1 file' "$tmp/lint-fix.log"
if grep -n '[[:blank:]]$' "$tmp/project/src/main.enq"; then
    echo "lint --fix left trailing whitespace behind" >&2
    exit 1
fi
(cd "$tmp/project" && "$compiler" lint --deny trailing-whitespace) > "$tmp/lint-clean.log" 2>&1
(cd "$tmp/project" && "$compiler" run) > "$tmp/run-before-format.log" 2>&1

# `analyze` remains executable for compatibility, but is deprecated
# immediately and delegates to the same lint behavior.
set +e
(cd "$tmp/project" && "$compiler" analyze --deny missing-public-docstring) > "$tmp/analyze.log" 2>&1
analyze_code=$?
set -e
test "$analyze_code" -eq 0
grep -q "warning: 'encore analyze' is deprecated; use 'encore lint'" "$tmp/analyze.log"
grep -q 'Linted 1 module' "$tmp/analyze.log"

# The formatter is syntax-aware, preserves comments and docstrings, and is
# idempotent. Check mode reports drift without writing files.
before_check=$(file_hash "$tmp/project/src/main.enq")
set +e
(cd "$tmp/project" && "$compiler" format --check) > "$tmp/format-check.log" 2>&1
format_check_code=$?
set -e
test "$format_check_code" -eq 1
grep -q 'Would format 1 file' "$tmp/format-check.log"
test "$before_check" = "$(file_hash "$tmp/project/src/main.enq")"

(cd "$tmp/project" && "$compiler" format) > "$tmp/format.log" 2>&1
grep -q 'Formatted 1 file' "$tmp/format.log"
grep -q '^//! Exercises the shared tooling foundation\.$' "$tmp/project/src/main.enq"
grep -q '^/// Adds two values\.$' "$tmp/project/src/main.enq"
grep -q '^pub fn add(lhs: u32, rhs: u32) -> u32 {' "$tmp/project/src/main.enq"
grep -q '^    ret lhs + rhs$' "$tmp/project/src/main.enq"
if ! grep -q '^    let value: u32 = add(1_u32, 2_u32)$' "$tmp/project/src/main.enq"; then
    echo "formatter produced unexpected source:" >&2
    sed -n '1,120p' "$tmp/project/src/main.enq" >&2
    exit 1
fi
grep -q '^    if value != 3_u32 {' "$tmp/project/src/main.enq"
grep -q '^        ret 1_u32$' "$tmp/project/src/main.enq"
formatted_hash=$(file_hash "$tmp/project/src/main.enq")
(cd "$tmp/project" && "$compiler" format) > "$tmp/format-again.log" 2>&1
test "$formatted_hash" = "$(file_hash "$tmp/project/src/main.enq")"
grep -q 'Formatted 0 files' "$tmp/format-again.log"
(cd "$tmp/project" && "$compiler" format --check) > "$tmp/format-clean.log" 2>&1
grep -q 'Would format 0 files' "$tmp/format-clean.log"
(cd "$tmp/project" && "$compiler" check) > "$tmp/formatted-check.log" 2>&1
(cd "$tmp/project" && "$compiler" run) > "$tmp/run-after-format.log" 2>&1

# Formatting invalid input is transactional: report diagnostics and leave the
# original bytes untouched.
cat > "$tmp/project/src/broken.enq" <<'EOF'
fn broken( {
EOF
broken_hash=$(file_hash "$tmp/project/src/broken.enq")
set +e
"$compiler" lint "$tmp/project/src/broken.enq" > "$tmp/broken-lint.log" 2>&1
broken_lint_code=$?
set -e
test "$broken_lint_code" -eq 1
grep -q 'error\[unclosed-parenthesis\]' "$tmp/broken-lint.log"
set +e
"$compiler" format "$tmp/project/src/broken.enq" > "$tmp/broken.log" 2>&1
broken_code=$?
set -e
test "$broken_code" -eq 1
if ! grep -q 'error\[' "$tmp/broken.log"; then
    echo "invalid-source formatter diagnostic is missing a stable code:" >&2
    sed -n '1,120p' "$tmp/broken.log" >&2
    exit 1
fi
test "$broken_hash" = "$(file_hash "$tmp/project/src/broken.enq")"

printf 'shared check, lint, and formatter integration: ok\n'

#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-analyzer.sh <encore-compiler>" >&2
    exit 2
fi

compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

"$compiler" lint --help > "$tmp/help.log"
grep -q 'Usage: encore lint \[options\] \[path\]' "$tmp/help.log"

set +e
"$compiler" lint --deny unknown-rule > "$tmp/unknown-rule.log" 2>&1
unknown_rule_code=$?
set -e
test "$unknown_rule_code" -eq 2
grep -q "unknown lint rule 'unknown-rule'" "$tmp/unknown-rule.log"

mkdir -p "$tmp/documented/src"
cat > "$tmp/documented/encore.toml" <<'EOF'
[project]
name = "documented"
version = "0.0.0"
dependencies = []
EOF
cat > "$tmp/documented/src/lib.enq" <<'EOF'
//! A fully documented library.

/// A documented value.
pub struct Value {
    /// The stored number.
    number: u32
}

/// Returns a value.
pub fn value() -> Value { ret Value{1_u32} }
EOF
(cd "$tmp/documented" && "$compiler" lint) > "$tmp/documented.log" 2>&1
grep -q 'Linted 1 module' "$tmp/documented.log"
if grep -q 'missing-.*docstring' "$tmp/documented.log"; then
    echo "documented declarations must not produce docstring diagnostics" >&2
    exit 1
fi

mkdir -p "$tmp/missing/src"
cat > "$tmp/missing/encore.toml" <<'EOF'
[project]
name = "missing"
version = "0.0.0"
dependencies = []
EOF
cat > "$tmp/missing/src/lib.enq" <<'EOF'
pub struct Packet {
    payload: u32
}

pub enum State {
    Ready
}

pub trait Service {
    fn call(self: Self) -> u32
}
EOF

# Warnings are visible but do not fail a local analysis run by default.
(cd "$tmp/missing" && "$compiler" lint) > "$tmp/warn.log" 2>&1
grep -q 'warning\[missing-module-docstring\]' "$tmp/warn.log"
if grep -q 'missing-public-docstring' "$tmp/warn.log"; then
    echo "missing-public-docstring must be disabled by default" >&2
    exit 1
fi

# Command-line levels override defaults and determine the exit status.
set +e
(cd "$tmp/missing" && "$compiler" lint --allow missing-module-docstring --deny missing-public-docstring) > "$tmp/deny.log" 2>&1
deny_code=$?
set -e
test "$deny_code" -eq 1
if grep -q 'missing-module-docstring' "$tmp/deny.log"; then
    echo "--allow must suppress the selected rule" >&2
    exit 1
fi
grep -q 'error\[missing-public-docstring\]' "$tmp/deny.log"

# Project configuration is read from encore.toml.
cat >> "$tmp/missing/encore.toml" <<'EOF'

[lint.rules]
missing-module-docstring = "allow"
missing-public-docstring = "deny"
EOF
set +e
(cd "$tmp/missing" && "$compiler" lint) > "$tmp/config.log" 2>&1
config_code=$?
set -e
test "$config_code" -eq 1
grep -q 'error\[missing-public-docstring\]' "$tmp/config.log"
if grep -q 'missing-module-docstring' "$tmp/config.log"; then
    echo "manifest rule levels must be applied" >&2
    exit 1
fi

# Machine-readable output contains stable paths, locations, severities and codes.
set +e
(cd "$tmp/missing" && "$compiler" lint --format json) > "$tmp/json.log" 2>&1
json_code=$?
set -e
test "$json_code" -eq 1
grep -q '"path":".*src/lib.enq"' "$tmp/json.log"
grep -q '"severity":"error"' "$tmp/json.log"
grep -q '"code":"missing-public-docstring"' "$tmp/json.log"

# A selected source path limits reporting without creating a temporary project.
cat > "$tmp/missing/src/clean.enq" <<'EOF'
//! A documented auxiliary module.

/// Returns zero.
pub fn clean() -> u32 { ret 0_u32 }
EOF
(cd "$tmp/missing" && "$compiler" lint --allow missing-module-docstring --warn missing-public-docstring src/clean.enq) > "$tmp/path.log" 2>&1
if grep -q 'missing-public-docstring' "$tmp/path.log"; then
    echo "path selection must exclude diagnostics from other modules" >&2
    exit 1
fi

# The compatibility alias is explicitly deprecated and delegates to lint.
(cd "$tmp/documented" && "$compiler" analyze) > "$tmp/deprecated.log" 2>&1
grep -q "warning: 'encore analyze' is deprecated; use 'encore lint'" "$tmp/deprecated.log"
grep -q 'Linted 1 module' "$tmp/deprecated.log"

printf 'analyzer CLI integration: ok\n'

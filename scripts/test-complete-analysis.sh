#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-complete-analysis.sh <encore-compiler>" >&2
    exit 2
fi

compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

mkdir -p "$tmp/project/src/model"
mkdir -p "$tmp/dependency/src"

cat > "$tmp/dependency/encore.toml" <<'EOF'
[project]
name = "analysis_dependency"
version = "0.0.0"
dependencies = []
EOF

cat > "$tmp/dependency/src/lib.enq" <<'EOF'
pub fn dependency_value() -> u32 { ret 1_u32 }
EOF

cat > "$tmp/project/encore.toml" <<'EOF'
[project]
name = "semantic_fixture"
version = "0.0.0"
dependencies = []

[lint]
default = "allow"
dependencies = "allow"
cap = "deny"

[lint.rules]
unused-imports = "deny"
unused-variables = "warn"
unreachable-code = "deny"
missing-public-docstring = "allow"
missing-module-docstring = "allow"
trailing-whitespace = "allow"

[format]
line-width = 40
indent-width = 2
newline-style = "lf"
trailing-comma = "vertical"
reorder-imports = true
format-docstrings = true
EOF

cat > "$tmp/project/src/model/mod.enq" <<'EOF'
pub struct User {
    name: str
}

pub trait Named {
    fn name(self: Self) -> str
}

impl Named for User {
    fn name(self: User) -> str { ret self.name }
}

pub fn identity[T](value: T) -> T { ret value }
EOF

cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::{User, Named, identity}

fn main() -> u32 {
    let user = User {"Ada"}
    let value: str = identity(user.name())
    if value == "Ada" { ret 0_u32 }
    ret 1_u32
}
EOF

# Cross-module definitions, imports, generic substitution, fields, methods and
# trait implementations are resolved by the shared semantic engine.
if ! (cd "$tmp/project" && "$compiler" check) > "$tmp/valid.log" 2>&1; then
    cat "$tmp/valid.log" >&2
    exit 1
fi
grep -q 'Checked 2 modules' "$tmp/valid.log"
test ! -e "$tmp/project/target"

# A cross-module type error contains a primary source label, a secondary label
# pointing at the declaration which established the expected type, and help.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::identity

fn main() -> u32 {
    let expected: str = "answer"
    expected = identity(42_u32)
    ret 0_u32
}
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/type-error.log" 2>&1
type_code=$?
set -e
test "$type_code" -eq 1
grep -q 'error\[assignment-type-mismatch\]:' "$tmp/type-error.log"
grep -q -- '--> .*src/main.enq:5:' "$tmp/type-error.log"
grep -q 'expected `str`, found `u32`' "$tmp/type-error.log"
grep -q 'expected because of this binding' "$tmp/type-error.log"
grep -q '= help:' "$tmp/type-error.log"
test "$(grep -c '^┌' "$tmp/type-error.log")" -ge 2
test "$(grep -c '^└' "$tmp/type-error.log")" -ge 2

set +e
(cd "$tmp/project" && "$compiler" build) > "$tmp/build-type-error.log" 2>&1
build_type_code=$?
set -e
test "$build_type_code" -eq 1
grep -q 'error\[assignment-type-mismatch\]:' "$tmp/build-type-error.log"
grep -q -- '--> .*src/main.enq:5:' "$tmp/build-type-error.log"

# JSON diagnostics preserve all structured children and suggestions instead of
# flattening the terminal rendering into a single message.
set +e
(cd "$tmp/project" && "$compiler" check --format json) > "$tmp/type-error.json" 2>&1
json_code=$?
set -e
test "$json_code" -eq 1
grep -q '"code":"assignment-type-mismatch"' "$tmp/type-error.json"
grep -q '"labels":\[' "$tmp/type-error.json"
grep -q '"kind":"secondary"' "$tmp/type-error.json"
grep -q '"notes":\[' "$tmp/type-error.json"
grep -q '"suggestions":\[' "$tmp/type-error.json"
grep -q '"applicability":"' "$tmp/type-error.json"

# Resolver failures distinguish modules, types, values and methods, and offer a
# nearest-name suggestion when one is unambiguous.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::User

fn main() -> u32 {
    let user = User {"Ada"}
    let label = user.nmae()
    ret 0_u32
}
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/name-error.log" 2>&1
name_code=$?
set -e
test "$name_code" -eq 1
grep -q 'error\[unknown-method\]:' "$tmp/name-error.log"
grep -q 'no method named `nmae`' "$tmp/name-error.log"
grep -q 'did you mean `name`' "$tmp/name-error.log"

# Import, type and value namespaces are resolved by the shared DefMap query,
# rather than by an LSP-only token pass.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::missing::Thing

fn main() -> u32 {
    let value: MissingType = missing_function()
    ret 0_u32
}
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/resolution-error.log" 2>&1
resolution_code=$?
set -e
test "$resolution_code" -eq 1
grep -q 'error\[unresolved-import\]:' "$tmp/resolution-error.log"
grep -q 'error\[unknown-type\]:' "$tmp/resolution-error.log"
grep -q 'error\[unresolved-call\]:' "$tmp/resolution-error.log"

# A declaration merely existing elsewhere in the workspace does not make it
# visible. DefMap scope, not a global name index, controls resolution.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::User

fn main() -> u32 {
    let user = User {"Ada"}
    let value = identity(user.name)
    ret 0_u32
}
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/unimported-name.log" 2>&1
unimported_code=$?
set -e
test "$unimported_code" -eq 1
grep -q 'error\[unresolved-call\]:' "$tmp/unimported-name.log"
grep -q 'cannot find function `identity`' "$tmp/unimported-name.log"

# Control-flow analysis rejects a non-void function whose fallthrough path has
# no return value.
cat > "$tmp/project/src/main.enq" <<'EOF'
fn incomplete(flag: bool) -> u32 {
    if flag { ret 1_u32 }
}

fn main() -> u32 { ret incomplete(true) }
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/missing-return.log" 2>&1
missing_return_code=$?
set -e
test "$missing_return_code" -eq 1
grep -q 'error\[missing-return\]:' "$tmp/missing-return.log"
grep -q 'not every control-flow path returns a value' "$tmp/missing-return.log"

# Checks still owned by the mature lowering validator use the same terminal
# framing and emit valid structured JSON instead of a one-line side channel.
set +e
"$compiler" check "$repo_root/tests/negative_try_operand.enq" > "$tmp/lowering-terminal.log" 2>&1
lowering_terminal_code=$?
"$compiler" check "$repo_root/tests/negative_try_operand.enq" --format json > "$tmp/lowering-json.log" 2>&1
lowering_json_code=$?
set -e
test "$lowering_terminal_code" -eq 1
test "$lowering_json_code" -eq 1
grep -q 'error\[invalid-try-operand\]:' "$tmp/lowering-terminal.log"
grep -q -- '--> .*negative_try_operand.enq:' "$tmp/lowering-terminal.log"
grep -q '^┌' "$tmp/lowering-terminal.log"
grep -q '^└' "$tmp/lowering-terminal.log"
grep -q '"code":"invalid-try-operand"' "$tmp/lowering-json.log"
grep -q '"labels":\[' "$tmp/lowering-json.log"
grep -q '"notes":\[' "$tmp/lowering-json.log"

# Trait obligations are checked by the same declaration query, including
# missing methods and signature mismatches.
cat > "$tmp/project/src/main.enq" <<'EOF'
trait Render {
    fn render(self: Self, width: u32) -> str
    fn size(self: Self) -> u32
}

struct Widget {}

impl Render for Widget {
    fn render(self: Widget, width: str) -> str { ret width }
}

fn main() -> u32 { ret 0_u32 }
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/trait-obligation.log" 2>&1
trait_obligation_code=$?
set -e
test "$trait_obligation_code" -eq 1
grep -q 'error\[trait-method-signature-mismatch\]:' "$tmp/trait-obligation.log"
grep -q 'error\[missing-trait-method\]:' "$tmp/trait-obligation.log"
grep -q 'trait method declared here' "$tmp/trait-obligation.log"

# Composite expression inference and call/field validation use the same typed
# HIR rather than falling back to unknown string types.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::User

fn takes(value: u32) -> u32 { ret value }

fn main() -> u32 {
    let tuple: (u32, str) = (1_u32, "one")
    let array: [u32; 2] = [1_u32, 2_u32]
    let branch = if true { 1_u32 } else { "wrong" }
    let mixed = [1_u32, "wrong"]
    let user = User {"Ada"}
    let field = user.naem
    let method = user.name(1_u32)
    let call = takes("wrong")
    let missing = valuu
    let invalid_binary = "wrong" - true
    ret tuple.0 + array[0_usize]
}
EOF
set +e
(cd "$tmp/project" && "$compiler" check) > "$tmp/composite-error.log" 2>&1
composite_code=$?
set -e
test "$composite_code" -eq 1
grep -q 'error\[branch-type-mismatch\]:' "$tmp/composite-error.log"
grep -q 'error\[collection-element-type-mismatch\]:' "$tmp/composite-error.log"
grep -q 'error\[unknown-field\]:' "$tmp/composite-error.log"
grep -q 'did you mean `name`' "$tmp/composite-error.log"
grep -q 'error\[argument-mismatch\]:' "$tmp/composite-error.log"
grep -q 'error\[method-arity-mismatch\]:' "$tmp/composite-error.log"
grep -q 'error\[unknown-variable\]:' "$tmp/composite-error.log"
grep -q 'error\[binary-operand-type-mismatch\]:' "$tmp/composite-error.log"

# Lint levels and groups are loaded by the shared manifest layer. CLI options
# override the manifest, while the configured cap prevents escalation beyond it.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::User
import semantic_fixture::model::identity

fn main() -> u32 {
    let unused = 1_u32
    ret 0_u32
}
EOF
set +e
(cd "$tmp/project" && "$compiler" lint) > "$tmp/lint-manifest.log" 2>&1
lint_code=$?
set -e
test "$lint_code" -eq 1
grep -q 'error\[unused-imports\]' "$tmp/lint-manifest.log"
grep -q 'warning\[unused-variables\]' "$tmp/lint-manifest.log"
grep -q -- '--> .*src/main.enq:' "$tmp/lint-manifest.log"
grep -q '= help:' "$tmp/lint-manifest.log"

(cd "$tmp/project" && "$compiler" lint --allow unused-imports --allow unused-variables) > "$tmp/lint-cli.log" 2>&1
grep -q 'Linted 2 modules' "$tmp/lint-cli.log"

# Every advertised semantic lint rule is backed by implementation, not only a
# manifest entry.
cat > "$tmp/project/src/main.enq" <<'EOF'
fn unused_helper() -> u32 { ret 1_u32 }

fn main() -> u32 {
    let mut value = 0_u32
    if true { let _kept = value }
    match true {
        true => {}
        true => {}
        _ => {}
        false => {}
    }
    ret value
}
EOF
set +e
(cd "$tmp/project" && "$compiler" lint \
    --deny unused-mut \
    --deny dead-code \
    --deny redundant-condition \
    --deny unreachable-patterns \
    --allow missing-module-docstring) > "$tmp/lint-semantic.log" 2>&1
semantic_lint_code=$?
set -e
test "$semantic_lint_code" -eq 1
grep -q 'error\[unused-mut\]' "$tmp/lint-semantic.log"
grep -q 'error\[dead-code\]' "$tmp/lint-semantic.log"
grep -q 'error\[redundant-condition\]' "$tmp/lint-semantic.log"
grep -q 'error\[unreachable-patterns\]' "$tmp/lint-semantic.log"

# Formatter configuration is project data shared with CLI and LSP. The
# manifest indent width must affect output, and formatting remains idempotent.
cat > "$tmp/project/src/main.enq" <<'EOF'
import semantic_fixture::model::identity
import semantic_fixture::model::User

///      Entry point.
fn main()->u32{
if true{
let value = identity("a very long value") + identity("and another long value")
ret 0_u32
}
ret 1_u32
}

fn add(
first:u32,
second:u32
)->u32{ret first+second}
EOF
(cd "$tmp/project" && "$compiler" format) > "$tmp/format.log" 2>&1
test "$(sed -n '1p' "$tmp/project/src/main.enq")" = 'import semantic_fixture::model::User'
test "$(sed -n '2p' "$tmp/project/src/main.enq")" = 'import semantic_fixture::model::identity'
grep -q '^/// Entry point\.$' "$tmp/project/src/main.enq"
grep -q '^  if true {' "$tmp/project/src/main.enq"
grep -q '^    ret 0_u32$' "$tmp/project/src/main.enq"
grep -q '^  second: u32,$' "$tmp/project/src/main.enq"
test "$(awk 'length($0) > 55 { count++ } END { print count + 0 }' "$tmp/project/src/main.enq")" -eq 0
cp "$tmp/project/src/main.enq" "$tmp/formatted.enq"
if ! (cd "$tmp/project" && "$compiler" format) > "$tmp/format-again.log" 2>&1; then
    cat "$tmp/format-again.log" >&2
    exit 1
fi
cmp "$tmp/formatted.enq" "$tmp/project/src/main.enq"
grep -q 'Formatted 0 files' "$tmp/format-again.log"

# Unknown configuration keys and invalid rule levels fail loudly; typos must
# never be silently ignored.
cp "$tmp/project/encore.toml" "$tmp/valid-manifest.toml"
cat >> "$tmp/project/encore.toml" <<'EOF'
unknown-option = true
EOF
set +e
(cd "$tmp/project" && "$compiler" format --check) > "$tmp/config-error.log" 2>&1
config_code=$?
set -e
test "$config_code" -eq 2
grep -q 'error\[manifest\].*unknown formatter option' "$tmp/config-error.log"
mv "$tmp/valid-manifest.toml" "$tmp/project/encore.toml"

# Package mutations update only [project].dependencies and preserve all
# analysis/formatter policy verbatim.
(cd "$tmp/project" && "$compiler" add "path@../dependency") > "$tmp/add.log" 2>&1
grep -q '^\[lint\]$' "$tmp/project/encore.toml"
grep -q '^unused-imports = "deny"$' "$tmp/project/encore.toml"
grep -q '^\[format\]$' "$tmp/project/encore.toml"
grep -q '^indent-width = 2$' "$tmp/project/encore.toml"

printf 'complete semantic analysis, diagnostics, lint, and formatter contracts: ok\n'

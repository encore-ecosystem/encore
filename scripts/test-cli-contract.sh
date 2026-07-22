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

for command in build run test analyze init add sync update install target; do
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

for invocation in "build --unknown" "build --target" "test --filter" "analyze --deny" "analyze one two" "init extra" "add" "sync extra" "update extra" "install one two" "target one two"; do
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
grep -q '^error\[manifest\]:' "$tmp/run-args.log"
if grep -q '^panic:' "$tmp/run-args.log"; then
    echo "project input errors must not be reported as compiler panics" >&2
    exit 1
fi

mkdir -p "$tmp/invalid-manifest/src"
cat > "$tmp/invalid-manifest/encore.toml" <<'EOF'
[project]
name = "invalid_manifest"
version = "0.0.0"
dependencies = []

[features]
default = "fonts"
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/invalid-manifest/src/main.enq"
set +e
(cd "$tmp/invalid-manifest" && "$compiler" build) > "$tmp/invalid-manifest.log" 2>&1
invalid_manifest_code=$?
set -e
test "$invalid_manifest_code" -eq 1
grep -q '^error\[manifest\]: Feature' "$tmp/invalid-manifest.log"

mkdir -p "$tmp/missing-workspace/src"
cat > "$tmp/missing-workspace/encore.toml" <<'EOF'
[project]
name = "missing_workspace"
version = "0.0.0"
dependencies = ["workspace@absent"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/missing-workspace/src/main.enq"
set +e
(cd "$tmp/missing-workspace" && "$compiler" build) > "$tmp/missing-workspace.log" 2>&1
missing_workspace_code=$?
set -e
test "$missing_workspace_code" -eq 1
grep -q '^error\[workspace\]: Unable to find workspace@absent' "$tmp/missing-workspace.log"

set +e
(cd "$tmp" && "$compiler" target fictional-unknown-none) > "$tmp/target.log" 2>&1
target_code=$?
set -e
test "$target_code" -eq 1
grep -q "unsupported target architecture 'fictional'" "$tmp/target.log"

# The shared semantic query layer must reject a typed body before EHIR
# lowering, while accepting the equivalent correctly typed project.
mkdir -p "$tmp/semantic-valid/src" "$tmp/semantic-invalid/src"
cat > "$tmp/semantic-valid/encore.toml" <<'EOF'
[project]
name = "semantic_valid"
version = "0.0.0"
dependencies = []
EOF
cat > "$tmp/semantic-valid/src/main.enq" <<'EOF'
fn value() -> u32 { ret 42_u32 }
fn main() -> u32 { let answer: u32 = value() ret answer }
EOF
cp "$tmp/semantic-valid/encore.toml" "$tmp/semantic-invalid/encore.toml"
sed 's/semantic_valid/semantic_invalid/' "$tmp/semantic-invalid/encore.toml" > "$tmp/semantic-invalid/encore.toml.next"
mv "$tmp/semantic-invalid/encore.toml.next" "$tmp/semantic-invalid/encore.toml"
cat > "$tmp/semantic-invalid/src/main.enq" <<'EOF'
fn value() -> u32 { ret 42_u32 }
fn main() -> u32 { let answer: str = value() ret 0_u32 }
EOF
(cd "$tmp/semantic-valid" && "$compiler" build) > "$tmp/semantic-valid.log" 2>&1
set +e
(cd "$tmp/semantic-invalid" && "$compiler" build) > "$tmp/semantic-invalid.log" 2>&1
semantic_invalid_code=$?
set -e
test "$semantic_invalid_code" -eq 1
grep -q 'error\[type-mismatch\]' "$tmp/semantic-invalid.log"
grep -q 'semantic checks failed' "$tmp/semantic-invalid.log"
if grep -q 'Compiling semantic_invalid' "$tmp/semantic-invalid.log"; then
    echo "semantic diagnostics must stop the build before EHIR lowering" >&2
    exit 1
fi

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
grep -q '^version = 2$' "$tmp/project/encore.lock"
grep -q '^name = "fixture_dependency"$' "$tmp/project/encore.lock"
grep -q '^ref = "path@../dependency"$' "$tmp/project/encore.lock"
grep -q '^version = "1.2.3"$' "$tmp/project/encore.lock"
grep -q '^ref = "sys@core"$' "$tmp/project/encore.lock"
if grep -Fq "$tmp" "$tmp/project/encore.lock"; then
    echo "encore.lock contains a machine-specific absolute path" >&2
    exit 1
fi

# Distribution-local workspace references with the same text must not collapse
# across package boundaries.
mkdir -p "$tmp/distribution-project/src" "$tmp/distribution-project/workspace/shared/src"
mkdir -p "$tmp/other-distribution/src" "$tmp/other-distribution/workspace/shared/src"
cat > "$tmp/distribution-project/encore.toml" <<'EOF'
[project]
name = "distribution_project"
version = "0.0.0"
dependencies = ["workspace@shared", "path@../other-distribution"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/distribution-project/src/main.enq"
cat > "$tmp/distribution-project/workspace/shared/encore.toml" <<'EOF'
[project]
name = "workspace_shared"
version = "1.0.0"
dependencies = []
EOF
printf 'pub fn workspace_value() -> u32 { ret 1_u32 }\n' > "$tmp/distribution-project/workspace/shared/src/lib.enq"
cat > "$tmp/other-distribution/encore.toml" <<'EOF'
[project]
name = "other_distribution"
version = "1.0.0"
dependencies = ["workspace@shared"]
EOF
printf 'pub fn other() -> u32 { ret 2_u32 }\n' > "$tmp/other-distribution/src/lib.enq"
cat > "$tmp/other-distribution/workspace/shared/encore.toml" <<'EOF'
[project]
name = "other_shared"
version = "1.0.0"
dependencies = []
EOF
printf 'pub fn other_shared_value() -> u32 { ret 3_u32 }\n' > "$tmp/other-distribution/workspace/shared/src/lib.enq"
(cd "$tmp/distribution-project" && "$compiler" sync) > "$tmp/distribution-sync.log"
test "$(grep -c '^ref = "workspace@shared"$' "$tmp/distribution-project/encore.lock")" -eq 2
grep -q '^name = "workspace_shared"$' "$tmp/distribution-project/encore.lock"
grep -q '^name = "other_shared"$' "$tmp/distribution-project/encore.lock"
(cd "$tmp/distribution-project" && "$compiler" build) > "$tmp/distribution-build.log"

mkdir -p "$tmp/cycle-project/src" "$tmp/cycle-project/workspace/alpha/src" "$tmp/cycle-project/workspace/beta/src"
cat > "$tmp/cycle-project/encore.toml" <<'EOF'
[project]
name = "cycle_project"
version = "0.0.0"
dependencies = ["workspace@alpha"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/cycle-project/src/main.enq"
cat > "$tmp/cycle-project/workspace/alpha/encore.toml" <<'EOF'
[project]
name = "cycle_alpha"
version = "1.0.0"
dependencies = ["workspace@beta"]
EOF
printf 'pub fn alpha() -> u32 { ret 1_u32 }\n' > "$tmp/cycle-project/workspace/alpha/src/lib.enq"
cat > "$tmp/cycle-project/workspace/beta/encore.toml" <<'EOF'
[project]
name = "cycle_beta"
version = "1.0.0"
dependencies = ["workspace@alpha"]
EOF
printf 'pub fn beta() -> u32 { ret 2_u32 }\n' > "$tmp/cycle-project/workspace/beta/src/lib.enq"
set +e
(cd "$tmp/cycle-project" && "$compiler" build) > "$tmp/cycle.log" 2>&1
cycle_code=$?
set -e
test "$cycle_code" -ne 0
grep -q 'Dependency cycle while loading refrain' "$tmp/cycle.log"

# Registry packages are sparse metadata entries backed by immutable release
# archives. A distribution may publish private workspace@ refrains, and its
# lockfile must work after the remote index becomes unavailable.
mkdir -p "$tmp/registry-package/src" "$tmp/registry-package/workspace/internal/src" "$tmp/index/re" "$tmp/registry-project/src" "$tmp/registry-cache"
cat > "$tmp/registry-package/encore.toml" <<'EOF'
[project]
name = "registry_fixture"
version = "1.2.3"
dependencies = ["workspace@internal"]
EOF
printf 'pub fn answer() -> u32 { ret 42_u32 }\n' > "$tmp/registry-package/src/lib.enq"
cat > "$tmp/registry-package/workspace/internal/encore.toml" <<'EOF'
[project]
name = "registry_fixture_internal"
version = "1.2.3"
dependencies = []
EOF
printf 'pub fn internal_answer() -> u32 { ret 42_u32 }\n' > "$tmp/registry-package/workspace/internal/src/lib.enq"
(cd "$tmp/registry-package" && tar -czf "$tmp/registry_fixture-1.2.3.tar.gz" encore.toml src workspace)
if command -v sha256sum >/dev/null 2>&1; then
    registry_checksum=$(sha256sum "$tmp/registry_fixture-1.2.3.tar.gz" | awk '{print $1}')
else
    registry_checksum=$(shasum -a 256 "$tmp/registry_fixture-1.2.3.tar.gz" | awk '{print $1}')
fi
sed 's/version = "1.2.3"/version = "2.0.0"/' "$tmp/registry-package/encore.toml" > "$tmp/registry-package/encore.toml.next"
mv "$tmp/registry-package/encore.toml.next" "$tmp/registry-package/encore.toml"
(cd "$tmp/registry-package" && tar -czf "$tmp/registry_fixture-2.0.0.tar.gz" encore.toml src workspace)
if command -v sha256sum >/dev/null 2>&1; then
    registry_checksum_v2=$(sha256sum "$tmp/registry_fixture-2.0.0.tar.gz" | awk '{print $1}')
else
    registry_checksum_v2=$(shasum -a 256 "$tmp/registry_fixture-2.0.0.tar.gz" | awk '{print $1}')
fi
cat > "$tmp/index/re/registry_fixture.json" <<EOF
{"name":"registry_fixture","versions":[{"version":"1.2.3","archive":"file://$tmp/registry_fixture-1.2.3.tar.gz","checksum":"$registry_checksum","yanked":false}]}
EOF
cat > "$tmp/registry-project/encore.toml" <<'EOF'
[project]
name = "registry_project"
version = "0.0.0"
dependencies = []
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/registry-project/src/main.enq"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" add registry_fixture) > "$tmp/registry-add.log"
grep -q '"index@registry_fixture"' "$tmp/registry-project/encore.toml"
grep -q '^name = "registry_fixture"$' "$tmp/registry-project/encore.lock"
grep -q '^ref = "index@registry_fixture"$' "$tmp/registry-project/encore.lock"
grep -q '^version = "1.2.3"$' "$tmp/registry-project/encore.lock"
grep -q "^checksum = \"$registry_checksum\"$" "$tmp/registry-project/encore.lock"
grep -q '^name = "registry_fixture_internal"$' "$tmp/registry-project/encore.lock"
grep -q '^ref = "workspace@internal"$' "$tmp/registry-project/encore.lock"
grep -q '^source = "embedded@registry_fixture"$' "$tmp/registry-project/encore.lock"
grep -q '^path = "workspace/internal"$' "$tmp/registry-project/encore.lock"
grep -q "^distribution-checksum = \"$registry_checksum\"$" "$tmp/registry-project/encore.lock"

# A changed requirement must not reuse an incompatible entry from encore.lock.
cat > "$tmp/index/re/registry_fixture.json" <<EOF
{"name":"registry_fixture","versions":[{"version":"1.2.3","archive":"file://$tmp/registry_fixture-1.2.3.tar.gz","checksum":"$registry_checksum","yanked":false},{"version":"2.0.0","archive":"file://$tmp/registry_fixture-2.0.0.tar.gz","checksum":"$registry_checksum_v2","yanked":false}]}
EOF

# Backtracking must revise an earlier package choice when its transitive
# constraint conflicts with a dependency selected later in the root queue.
mkdir -p "$tmp/chooser-package/src" "$tmp/index/ch" "$tmp/backtrack-project/src"
cat > "$tmp/chooser-package/encore.toml" <<'EOF'
[project]
name = "chooser_fixture"
version = "1.0.0"
dependencies = ["index@registry_fixture@^1.0.0"]
EOF
printf 'pub fn choice() -> u32 { ret 1_u32 }\n' > "$tmp/chooser-package/src/lib.enq"
(cd "$tmp/chooser-package" && tar -czf "$tmp/chooser_fixture-1.0.0.tar.gz" encore.toml src)
if command -v sha256sum >/dev/null 2>&1; then
    chooser_checksum_v1=$(sha256sum "$tmp/chooser_fixture-1.0.0.tar.gz" | awk '{print $1}')
else
    chooser_checksum_v1=$(shasum -a 256 "$tmp/chooser_fixture-1.0.0.tar.gz" | awk '{print $1}')
fi
sed -e 's/version = "1.0.0"/version = "2.0.0"/' -e 's/\^1.0.0/\^2.0.0/' "$tmp/chooser-package/encore.toml" > "$tmp/chooser-package/encore.toml.next"
mv "$tmp/chooser-package/encore.toml.next" "$tmp/chooser-package/encore.toml"
(cd "$tmp/chooser-package" && tar -czf "$tmp/chooser_fixture-2.0.0.tar.gz" encore.toml src)
if command -v sha256sum >/dev/null 2>&1; then
    chooser_checksum_v2=$(sha256sum "$tmp/chooser_fixture-2.0.0.tar.gz" | awk '{print $1}')
else
    chooser_checksum_v2=$(shasum -a 256 "$tmp/chooser_fixture-2.0.0.tar.gz" | awk '{print $1}')
fi
cat > "$tmp/index/ch/chooser_fixture.json" <<EOF
{"name":"chooser_fixture","versions":[{"version":"1.0.0","archive":"file://$tmp/chooser_fixture-1.0.0.tar.gz","checksum":"$chooser_checksum_v1","yanked":false},{"version":"2.0.0","archive":"file://$tmp/chooser_fixture-2.0.0.tar.gz","checksum":"$chooser_checksum_v2","yanked":false}]}
EOF
cat > "$tmp/backtrack-project/encore.toml" <<'EOF'
[project]
name = "backtrack_project"
version = "0.0.0"
dependencies = ["index@chooser_fixture", "index@registry_fixture@^1.0.0"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/backtrack-project/src/main.enq"
(cd "$tmp/backtrack-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/backtrack-cache" "$compiler" sync --update) > "$tmp/registry-backtrack.log"
grep -A4 '^name = "chooser_fixture"$' "$tmp/backtrack-project/encore.lock" | grep -q '^version = "1.0.0"$'
grep -A4 '^name = "registry_fixture"$' "$tmp/backtrack-project/encore.lock" | grep -q '^version = "1.2.3"$'
test "$(grep -c '^name = "registry_fixture"$' "$tmp/backtrack-project/encore.lock")" -eq 1

mkdir -p "$tmp/locked-backtrack-project/src"
cat > "$tmp/locked-backtrack-project/encore.toml" <<'EOF'
[project]
name = "locked_backtrack_project"
version = "0.0.0"
dependencies = ["index@chooser_fixture"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/locked-backtrack-project/src/main.enq"
(cd "$tmp/locked-backtrack-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/locked-backtrack-cache" "$compiler" sync --update) > "$tmp/registry-locked-initial.log"
grep -A4 '^name = "chooser_fixture"$' "$tmp/locked-backtrack-project/encore.lock" | grep -q '^version = "2.0.0"$'
sed 's/"index@chooser_fixture"/"index@chooser_fixture", "index@registry_fixture@^1.0.0"/' "$tmp/locked-backtrack-project/encore.toml" > "$tmp/locked-backtrack-project/encore.toml.next"
mv "$tmp/locked-backtrack-project/encore.toml.next" "$tmp/locked-backtrack-project/encore.toml"
(cd "$tmp/locked-backtrack-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/locked-backtrack-cache" "$compiler" sync) > "$tmp/registry-locked-backtrack.log"
grep -A4 '^name = "chooser_fixture"$' "$tmp/locked-backtrack-project/encore.lock" | grep -q '^version = "1.0.0"$'

sed 's/index@registry_fixture/index@registry_fixture@^2.0.0/' "$tmp/registry-project/encore.toml" > "$tmp/registry-project/encore.toml.next"
mv "$tmp/registry-project/encore.toml.next" "$tmp/registry-project/encore.toml"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync) > "$tmp/registry-resolve-v2.log"
grep -q '^ref = "index@registry_fixture@\^2.0.0"$' "$tmp/registry-project/encore.lock"
grep -q '^version = "2.0.0"$' "$tmp/registry-project/encore.lock"

# A graph may contain only one version of a named registry package.
sed 's/"index@registry_fixture@\^2.0.0"/"index@registry_fixture@^1.0.0", "index@registry_fixture@^2.0.0"/' "$tmp/registry-project/encore.toml" > "$tmp/registry-project/encore.toml.next"
mv "$tmp/registry-project/encore.toml.next" "$tmp/registry-project/encore.toml"
set +e
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync --update) > "$tmp/registry-conflict.log" 2>&1
registry_conflict_code=$?
set -e
test "$registry_conflict_code" -ne 0
grep -q 'Unable to resolve registry_fixture: no version satisfies' "$tmp/registry-conflict.log"

# Compatible constraints are intersected before selecting a package version.
sed 's/"index@registry_fixture@\^1.0.0", "index@registry_fixture@\^2.0.0"/"index@registry_fixture@^1.0.0", "index@registry_fixture@<1.5.0"/' "$tmp/registry-project/encore.toml" > "$tmp/registry-project/encore.toml.next"
mv "$tmp/registry-project/encore.toml.next" "$tmp/registry-project/encore.toml"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync --update) > "$tmp/registry-intersection.log"
test "$(grep -c '^name = "registry_fixture"$' "$tmp/registry-project/encore.lock")" -eq 1
grep -q '^version = "1.2.3"$' "$tmp/registry-project/encore.lock"

mkdir -p "$tmp/transitive-project/src" "$tmp/transitive-project/parent-a/src" "$tmp/transitive-project/parent-b/src"
cat > "$tmp/transitive-project/encore.toml" <<'EOF'
[project]
name = "transitive_project"
version = "0.0.0"
dependencies = ["path@parent-a", "path@parent-b"]
EOF
cat > "$tmp/transitive-project/parent-a/encore.toml" <<'EOF'
[project]
name = "parent_a"
version = "0.0.0"
dependencies = ["index@registry_fixture@^1.0.0"]
EOF
cat > "$tmp/transitive-project/parent-b/encore.toml" <<'EOF'
[project]
name = "parent_b"
version = "0.0.0"
dependencies = ["index@registry_fixture@<1.5.0"]
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/transitive-project/src/main.enq"
printf 'pub fn value_a() -> u32 { ret 1_u32 }\n' > "$tmp/transitive-project/parent-a/src/lib.enq"
printf 'pub fn value_b() -> u32 { ret 2_u32 }\n' > "$tmp/transitive-project/parent-b/src/lib.enq"
(cd "$tmp/transitive-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync --update) > "$tmp/registry-transitive-intersection.log"
test "$(grep -c '^name = "registry_fixture"$' "$tmp/transitive-project/encore.lock")" -eq 1
grep -A4 '^name = "registry_fixture"$' "$tmp/transitive-project/encore.lock" | grep -q '^version = "1.2.3"$'

sed 's/"index@registry_fixture@\^1.0.0", "index@registry_fixture@<1.5.0"/"index@registry_fixture@^2.0.0"/' "$tmp/registry-project/encore.toml" > "$tmp/registry-project/encore.toml.next"
mv "$tmp/registry-project/encore.toml.next" "$tmp/registry-project/encore.toml"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync) > "$tmp/registry-restore-v2.log"
rm -rf "$tmp/index" "$tmp/registry_fixture-1.2.3.tar.gz" "$tmp/registry_fixture-2.0.0.tar.gz"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" sync) > "$tmp/registry-sync.log"
(cd "$tmp/registry-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/registry-cache" "$compiler" build) > "$tmp/registry-build.log"

# Registry archives cannot use links to escape their distribution root.
mkdir -p "$tmp/link-package/src" "$tmp/index/li" "$tmp/link-project/src"
cat > "$tmp/link-package/encore.toml" <<'EOF'
[project]
name = "link_fixture"
version = "1.0.0"
dependencies = []
EOF
printf 'pub fn value() -> u32 { ret 1_u32 }\n' > "$tmp/link-package/src/lib.enq"
ln -s /tmp "$tmp/link-package/workspace"
(cd "$tmp/link-package" && tar -czf "$tmp/link_fixture-1.0.0.tar.gz" encore.toml src workspace)
if command -v sha256sum >/dev/null 2>&1; then
    link_checksum=$(sha256sum "$tmp/link_fixture-1.0.0.tar.gz" | awk '{print $1}')
else
    link_checksum=$(shasum -a 256 "$tmp/link_fixture-1.0.0.tar.gz" | awk '{print $1}')
fi
cat > "$tmp/index/li/link_fixture.json" <<EOF
{"name":"link_fixture","versions":[{"version":"1.0.0","archive":"file://$tmp/link_fixture-1.0.0.tar.gz","checksum":"$link_checksum","yanked":false}]}
EOF
cat > "$tmp/link-project/encore.toml" <<'EOF'
[project]
name = "link_project"
version = "0.0.0"
dependencies = []
EOF
printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/link-project/src/main.enq"
set +e
(cd "$tmp/link-project" && ENCORE_INDEX_URL="file://$tmp/index" ENCORE_REGISTRY_CACHE="$tmp/link-cache" "$compiler" add link_fixture) > "$tmp/link.log" 2>&1
link_code=$?
set -e
test "$link_code" -ne 0
grep -q 'contains links or special files' "$tmp/link.log"

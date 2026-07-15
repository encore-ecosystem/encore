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
rm -rf "$tmp/index" "$tmp/registry_fixture-1.2.3.tar.gz"
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

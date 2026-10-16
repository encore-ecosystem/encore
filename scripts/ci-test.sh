#!/usr/bin/env bash
set -euo pipefail
compiler=${1:?stage3 compiler required}
repository=$PWD
run_id=${CI_TEST_RUN_ID:-compiler}
[[ "$run_id" =~ ^[a-zA-Z0-9-]+$ ]]
fixture="$repository/target/ci-tests/$run_id"
test ! -e "$fixture"
mkdir -p "$fixture"
cp -R src tests "$fixture/"
cp tests/ci/lib.enq "$fixture/src/lib.enq"
cp tests/ci/runtime.enq "$fixture/src/ci_runtime.enq"
cp tests/ci/pipeline.enq "$fixture/src/ci_pipeline.enq"
cp tests/ci/helpers.enq "$fixture/src/ci_helpers.enq"
cp tests/ci/cli.enq "$fixture/src/ci_cli.enq"
cp tests/ci/cache.enq "$fixture/src/ci_cache.enq"
cp tests/ci/self_update.enq "$fixture/src/ci_self_update.enq"
cp tests/ci/registry.enq "$fixture/src/ci_registry.enq"
cp tests/ci/build_scripts.enq "$fixture/src/ci_build_scripts.enq"
cp tests/ci/runtime.c "$fixture/runtime.c"
# Preserve source-relative package identities; do not expose CLI internals in
# the compiler's public library merely to discover their private unit tests.
sed 's|path@packages/|path@../../../packages/|g' encore.toml > "$fixture/encore.toml"
export ENCORE_TEST_COMPILER="$compiler"
export ENCORE_TEST_REPOSITORY="$repository"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    # The Encore subprocess API takes native paths, not Git Bash mount paths.
    export ENCORE_TEST_COMPILER="$(cygpath -m "$compiler")"
    export ENCORE_TEST_REPOSITORY="$(cygpath -m "$repository")"
    ;;
esac
(cd "$fixture" && "$compiler" test --report "$repository/target/test-report.json" "${@:2}")

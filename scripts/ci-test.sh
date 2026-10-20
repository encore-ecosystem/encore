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
if command -v cygpath >/dev/null 2>&1; then
  export ENCORE_TEST_COMPILER="$(cygpath -m "$compiler")"
  export ENCORE_TEST_REPOSITORY="$(cygpath -m "$repository")"
fi
if [[ "${CI_TEST_PREPARE_ONLY:-0}" == 1 ]]; then
  mkdir -p "$fixture/target"
  (cd "$fixture" && "$compiler" test --list --format json > target/test-inventory.json)
  (cd "$fixture" && "$compiler" test --_worker-harness --jobs "${CI_TEST_PREPARE_JOBS:-2}")
  python3 "$repository/scripts/ci-test-context.py" save "$compiler" "$fixture" \
    "$repository/target/prepared-test-harness"
  exit 0
fi
if [[ -n "${CI_TEST_HARNESS_CONTEXT:-}" ]]; then
  python3 "$repository/scripts/ci-test-context.py" restore "$compiler" "$fixture" "$CI_TEST_HARNESS_CONTEXT"
fi
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    # The Encore subprocess API takes native paths, not Git Bash mount paths.
    args_json=$(jq -cn --args '$ARGS.positional' -- "${@:2}")
    supervisor=$(cygpath -m "$repository/scripts/ci-test-windows.ps1")
    report=$(cygpath -m "$repository/target/test-report.json")
    (cd "$fixture" && MSYS2_ARG_CONV_EXCL='*' pwsh -NoProfile -NonInteractive \
      -File "$supervisor" -Compiler "$ENCORE_TEST_COMPILER" \
      -Report "$report" -ArgumentsJson "$args_json")
    exit $?
    ;;
esac
(cd "$fixture" && "$compiler" test --report "$repository/target/test-report.json" "${@:2}")

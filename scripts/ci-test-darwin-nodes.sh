#!/usr/bin/env bash
set -euo pipefail
compiler=${1:?stage3 compiler required}
mkdir -p target/darwin-node-diagnostics
export ENCORE_KEEP_TEMPS=1
export ENCORE_CI_CRASH_DIAGNOSTICS=1
export ENCORE_CODEGEN_PROFILE=1
status=0
for name in mutable_binding_identity branch_node_ownership nested_node_field_assignment stack_node_alignment; do
  run_id="darwin-node-${name//_/-}"
  if ! CI_TEST_RUN_ID="$run_id" bash scripts/ci-test.sh "$compiler" \
      --filter "tests/$name.enq" --jobs 2 --keep-build-artifacts; then
    status=1
  fi
  if [[ -f target/test-report.json ]]; then
    cp target/test-report.json "target/darwin-node-diagnostics/$name.json"
  fi
done
exit "$status"

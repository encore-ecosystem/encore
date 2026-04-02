#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
examples_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
host_bin="${ENCORE_HOST_BIN:-$root_dir/../.venv/bin/encore}"

toml_get() {
  local key="$1"
  local file="$2"
  awk -F'"' -v k="$key" '$1 ~ "^[[:space:]]*" k "[[:space:]]*=" { print $2 }' "$file" | tail -n 1
}

skip_host_build_reason() {
  local example="$1"
  case "$example" in
    heap) echo "host LLVM backend type mismatch for heap example"; return 0 ;;
  esac
  return 1
}

is_executable_target() {
  local target="$1"
  if [[ -z "$target" || "$target" == "auto" || "$target" == "executable" ]]; then
    return 0
  fi
  return 1
}

expected_exit_code() {
  local example="$1"
  case "$example" in
    hello) echo 0 ;;
    arithmetic) echo 42 ;;
    do_while) echo 62 ;;
    heap) echo 32 ;;
    latest) echo 15 ;;
    loop) echo 6 ;;
    refrains) echo 25 ;;
    structs) echo 14 ;;
    while) echo 5 ;;
    *) echo 0 ;;
  esac
}

if [[ ! -x "$host_bin" ]]; then
  echo "host encore binary is missing: $host_bin"
  echo "set ENCORE_HOST_BIN or install it in ../.venv/bin/encore"
  exit 1
fi

mapfile -t examples < <(find "$examples_dir" -mindepth 1 -maxdepth 1 -type d ! -name golden | sort)
if [[ ${#examples[@]} -eq 0 ]]; then
  echo "[exec] no examples found in $examples_dir"
  exit 1
fi

failed=0

for example_dir in "${examples[@]}"; do
  example="$(basename "$example_dir")"
  manifest="$example_dir/encore.toml"
  if [[ ! -f "$manifest" ]]; then
    echo "[exec] skip $example (no encore.toml)"
    continue
  fi

  project_name="$(toml_get name "$manifest")"
  target="$(toml_get target "$manifest")"
  profile="$(toml_get profile "$manifest")"
  if [[ -z "$project_name" ]]; then
    project_name="$example"
  fi
  if [[ -z "$profile" ]]; then
    profile="debug"
  fi

  if reason="$(skip_host_build_reason "$example")"; then
    echo "[exec] skip $example ($reason)"
    continue
  fi

  if ! is_executable_target "$target"; then
    echo "[exec] skip $example (target=$target)"
    continue
  fi

  echo "[exec] build $example"
  (
    cd "$example_dir"
    "$host_bin" build >/dev/null
  )

  binary_path="$example_dir/target/$profile/$project_name"
  if [[ ! -x "$binary_path" ]]; then
    echo "[exec] missing binary: $binary_path"
    failed=1
    continue
  fi

  expected="$(expected_exit_code "$example")"
  set +e
  "$binary_path" >/dev/null
  rc=$?
  set -e

  if [[ "$rc" -ne "$expected" ]]; then
    echo "[exec] unexpected exit code for $example: got $rc, expected $expected"
    failed=1
    continue
  fi

  echo "[exec] $example exit=$rc"
done

if [[ "$failed" -ne 0 ]]; then
  echo "[exec] smoke failed"
  exit 1
fi

echo "[exec] all executable examples passed"

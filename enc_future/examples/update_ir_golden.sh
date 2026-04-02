#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
examples_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
golden_dir="$examples_dir/golden"
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

resolve_ir_stem() {
  local project_name="$1"
  local target="$2"
  case "$target" in
    static_lib|dynamic_lib|shared_lib) echo "lib${project_name}" ;;
    *) echo "$project_name" ;;
  esac
}

if [[ ! -x "$host_bin" ]]; then
  echo "host encore binary is missing: $host_bin"
  echo "set ENCORE_HOST_BIN or install it in ../.venv/bin/encore"
  exit 1
fi

mkdir -p "$golden_dir"

mapfile -t examples < <(find "$examples_dir" -mindepth 1 -maxdepth 1 -type d ! -name golden | sort)
if [[ ${#examples[@]} -eq 0 ]]; then
  echo "[golden] no examples found in $examples_dir"
  exit 1
fi

for example_dir in "${examples[@]}"; do
  example="$(basename "$example_dir")"
  manifest="$example_dir/encore.toml"
  if [[ ! -f "$manifest" ]]; then
    echo "[golden] skip $example (no encore.toml)"
    continue
  fi

  project_name="$(toml_get name "$manifest")"
  target="$(toml_get target "$manifest")"
  profile="$(toml_get profile "$manifest")"
  if [[ -z "$project_name" ]]; then
    project_name="$example"
  fi
  if [[ -z "$target" ]]; then
    target="auto"
  fi
  if [[ -z "$profile" ]]; then
    profile="debug"
  fi

  if reason="$(skip_host_build_reason "$example")"; then
    echo "[golden] skip $example ($reason)"
    continue
  fi

  echo "[golden] build $example"
  (
    cd "$example_dir"
    "$host_bin" build >/dev/null
  )

  ir_stem="$(resolve_ir_stem "$project_name" "$target")"
  ir_path="$example_dir/target/$profile/llvm/$ir_stem.ir"
  if [[ ! -f "$ir_path" ]]; then
    echo "[golden] missing IR: $ir_path"
    exit 1
  fi

  cp "$ir_path" "$golden_dir/$example.ir"
  echo "[golden] updated $example.ir"
done

echo "[golden] update completed"

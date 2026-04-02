#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root_dir/target/debug/encore"
examples_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$bin" ]]; then
  echo "enc_future binary is missing: $bin"
  echo "build it first:"
  echo "  cd $root_dir && encore build"
  exit 1
fi

mapfile -t examples < <(find "$examples_dir" -mindepth 1 -maxdepth 1 -type d ! -name golden | sort)
if [[ ${#examples[@]} -eq 0 ]]; then
  echo "[smoke] no examples found in $examples_dir"
  exit 1
fi

for example_dir in "${examples[@]}"; do
  example="$(basename "$example_dir")"
  echo "[smoke] $example"
  (
    cd "$example_dir"
    "$bin" build
  )
done

echo "[smoke] all examples passed"

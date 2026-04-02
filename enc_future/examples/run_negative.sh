#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root_dir/target/debug/encore"
negative_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/negative" && pwd)"

if [[ ! -x "$bin" ]]; then
  echo "enc_future binary is missing: $bin"
  echo "build it first:"
  echo "  cd $root_dir && encore build"
  exit 1
fi

mapfile -t cases < <(find "$negative_dir" -mindepth 1 -maxdepth 1 -type d | sort)
if [[ ${#cases[@]} -eq 0 ]]; then
  echo "[negative] no cases found in $negative_dir"
  exit 1
fi

for case_dir in "${cases[@]}"; do
  case_name="$(basename "$case_dir")"
  log_file="$(mktemp)"
  echo "[negative] $case_name"

  set +e
  (
    cd "$case_dir"
    "$bin" build
  ) >"$log_file" 2>&1
  status=$?
  set -e

  if [[ $status -eq 0 ]]; then
    echo "[negative] expected failure but got success: $case_name"
    cat "$log_file"
    rm -f "$log_file"
    exit 1
  fi

  if [[ $status -ge 128 ]]; then
    signal=$((status - 128))
    echo "[negative] compiler crashed with signal $signal: $case_name"
    cat "$log_file"
    rm -f "$log_file"
    exit 1
  fi

  expected_file="$case_dir/expected.txt"
  if [[ -f "$expected_file" ]]; then
    expected="$(cat "$expected_file")"
    if ! grep -Fq "$expected" "$log_file"; then
      echo "[negative] expected message not found: $case_name"
      echo "[negative] expected substring: $expected"
      echo "[negative] output:"
      cat "$log_file"
      rm -f "$log_file"
      exit 1
    fi
  fi

  rm -f "$log_file"
done

echo "[negative] all cases passed"

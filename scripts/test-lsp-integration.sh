#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: test-lsp-integration.sh <encore-compiler>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
compiler="$compiler_dir/$(basename -- "$1")"

(cd "$repo_root/index/lsp" && "$compiler" build --profile debug)
lsp="$repo_root/index/lsp/target/debug/lsp"
if [ -x "$lsp.exe" ]; then
    lsp="$lsp.exe"
fi
python_command=${PYTHON:-python3}
if ! command -v "$python_command" >/dev/null 2>&1; then
    python_command=python
fi
"$python_command" "$repo_root/index/lsp/tests/docstrings.py" "$lsp"

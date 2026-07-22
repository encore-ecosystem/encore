#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

tracked_python=$(git ls-files '*.py' '*.pyi' 'pyproject.toml' 'requirements*.txt' 'setup.py' 'setup.cfg' |
    grep -Ev '(^benchmark/|/tests/)' || true)
if [ -n "$tracked_python" ]; then
    echo "Retired Python compiler files are still tracked:" >&2
    printf '%s\n' "$tracked_python" >&2
    exit 1
fi

if git grep -n -E '(^|[^[:alnum:]_-])(python[0-9.]*|pip[0-9.]*|encore-py)([^[:alnum:]_-]|$)' -- \
    '.github/**' 'scripts/**' 'install.sh' '*.enq' '*.c' '*.toml' \
    ':(exclude)scripts/verify-no-python.sh'
then
    echo "Production source or automation still invokes Python" >&2
    exit 1
fi

printf 'Verified native-only compiler sources and automation\n'

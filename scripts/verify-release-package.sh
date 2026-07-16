#!/usr/bin/env sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: verify-release-package.sh <archive> <target-triple> <version>" >&2
    exit 2
fi

archive_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
archive="$archive_dir/$(basename -- "$1")"
triple=$2
version=$3
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

tar -xf "$archive" -C "$tmp"
package_count=$(find "$tmp" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
test "$package_count" = "1"
package=$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)
test -n "$package"
test "$(basename -- "$package")" = "encore-${version}-${triple}"

test "$(cat "$package/VERSION")" = "$version"
case "$triple" in
    *-windows-*) binary="$package/bin/encore.exe" ;;
    *) binary="$package/bin/encore" ;;
esac
test -s "$binary"
test -f "$package/lib/encore/index/core/runtime.c"
test -f "$package/lib/encore/index/core/encore.toml"
test -f "$package/lib/encore/index/std/encore.toml"
test -f "$package/lib/encore/encore.toml"
test -f "$package/lib/encore/src/main.enq"
test -f "$package/lib/encore/src/target/mod.enq"
test -f "$package/share/doc/encore/LICENSE"
test -f "$package/share/doc/encore/README.md"

expected_index_packages='colorterm
core
ehir
ehir-llvm-backend
json
llvm
log
rich
std
toml'
actual_index_packages=$(find "$package/lib/encore/index" -mindepth 1 -maxdepth 1 -type d -exec basename '{}' \; | LC_ALL=C sort)
if [ "$actual_index_packages" != "$expected_index_packages" ]; then
    echo "Release package contains an unexpected compiler index closure" >&2
    printf 'expected:\n%s\nactual:\n%s\n' "$expected_index_packages" "$actual_index_packages" >&2
    exit 1
fi

if find "$package" -type l | grep -q .; then
    echo "Release package must not contain symbolic links" >&2
    exit 1
fi
if find "$package" -type d \( \( -name target ! -path '*/src/target' \) -o -name .git -o -name .venv -o -name __pycache__ \) | grep -q .; then
    echo "Release package contains a build or cache directory" >&2
    exit 1
fi
if find "$package" -type f \( -name '*.o' -o -name '*.obj' -o -name '*.ll' -o -name '*.ehir' -o -name '*.py' -o -name '*.pyc' \) | grep -q .; then
    echo "Release package contains a generated or retired Python file" >&2
    exit 1
fi

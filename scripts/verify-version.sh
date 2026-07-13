#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=$(cat "$repo_root/VERSION")
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'

manifest_version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/index/encore/encore.toml" | head -n 1)
pkg_version=$(sed -n 's/^pkgver=//p' "$repo_root/PKGBUILD" | head -n 1)
test "$manifest_version" = "$version"
test "$pkg_version" = "$version"
grep -Fq "console.println(\"encore $version\")" "$repo_root/index/encore/src/main.enq"
grep -Fq "The current development line is \`$version\`." "$repo_root/README.md"

if [ "$#" -gt 1 ]; then
    echo "usage: verify-version.sh [encore-compiler]" >&2
    exit 2
fi
if [ "$#" -eq 1 ]; then
    compiler_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
    compiler="$compiler_dir/$(basename -- "$1")"
    test "$($compiler --version)" = "encore $version"
fi

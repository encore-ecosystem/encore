#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=$(cat "$repo_root/VERSION")
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-(beta\.[0-9]+|nightly\.[0-9]{8}))?$'

manifest_version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo_root/encore.toml" | head -n 1)
pkg_version=$(sed -n 's/^pkgver=//p' "$repo_root/packaging/PKGBUILD.template" | head -n 1)
test "$manifest_version" = "$version"
case "$version" in *-*) ;; *) test "$pkg_version" = "$version" ;; esac
grep -Fq "pub fn compiler_version() -> str { ret \"$version\" }" "$repo_root/src/version.enq"
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

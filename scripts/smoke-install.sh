#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: smoke-install.sh <release-archive>" >&2
    exit 2
fi

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
archive_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
archive="$archive_dir/$(basename -- "$1")"
checksum="$archive.sha256"

if [ ! -f "$archive" ] || [ ! -f "$checksum" ]; then
    echo "archive and checksum are required" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir -p "$tmp/inspect"
tar -xf "$archive" -C "$tmp/inspect"
package_dir=$(find "$tmp/inspect" -mindepth 1 -maxdepth 1 -type d | head -n 1)
package_version=$(cat "$package_dir/VERSION")

ENCORE_HOME="$tmp/home" \
ENCORE_VERSION="$package_version" \
ENCORE_RELEASE_BASE_URL="file://$archive_dir" \
    "$repo_root/install.sh"

"$tmp/home/bin/encore" --version

set +e
mismatch_output=$(ENCORE_HOME="$tmp/mismatch" \
    ENCORE_VERSION=wrong-version \
    ENCORE_RELEASE_BASE_URL="file://$archive_dir" \
    "$repo_root/install.sh" 2>&1)
mismatch_code=$?
set -e
test "$mismatch_code" -ne 0
printf '%s\n' "$mismatch_output" | grep -q "Release version mismatch"

cp -R "$repo_root/examples/add_two_structs" "$tmp/project"
rm -rf "$tmp/project/target"
set +e
(
    cd "$tmp/project"
    "$tmp/home/bin/encore" build --profile debug
    ./target/debug/add_two_structs
)
code=$?
set -e
test "$code" -eq 12

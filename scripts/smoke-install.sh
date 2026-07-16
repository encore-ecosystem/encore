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

ENCORE_HOME="$tmp/home-v-prefix" \
ENCORE_VERSION="v$package_version" \
ENCORE_RELEASE_BASE_URL="file://$archive_dir" \
    "$repo_root/install.sh"
"$tmp/home-v-prefix/bin/encore" --version

printf 'stale\n' > "$tmp/home/VERSION"
ENCORE_RELEASE_BASE_URL="file://$archive_dir" \
    "$repo_root/install.sh" --update --version "$package_version" --install-dir "$tmp/home"
test "$(cat "$tmp/home/VERSION")" = "$package_version"

set +e
mismatch_output=$(ENCORE_HOME="$tmp/mismatch" \
    ENCORE_VERSION=wrong-version \
    ENCORE_RELEASE_BASE_URL="file://$archive_dir" \
    "$repo_root/install.sh" 2>&1)
mismatch_code=$?
set -e
test "$mismatch_code" -ne 0
printf '%s\n' "$mismatch_output" | grep -q "Release version mismatch"

mkdir -p "$tmp/bad-release" "$tmp/protected"
cp "$archive" "$tmp/bad-release/$(basename -- "$archive")"
printf '%064d  %s\n' 0 "$(basename -- "$archive")" > "$tmp/bad-release/$(basename -- "$checksum")"
printf 'keep\n' > "$tmp/protected/VERSION"
set +e
ENCORE_HOME="$tmp/protected" \
ENCORE_VERSION="$package_version" \
ENCORE_RELEASE_BASE_URL="file://$tmp/bad-release" \
    "$repo_root/install.sh" > "$tmp/checksum.log" 2>&1
checksum_code=$?
set -e
test "$checksum_code" -ne 0
grep -q "Checksum verification failed" "$tmp/checksum.log"
test "$(cat "$tmp/protected/VERSION")" = keep

# The installer must reject path traversal and links before extraction. GNU
# tar creates the traversal fixture; BSD tar still runs the link fixture.
if tar --help 2>&1 | grep -q -- '--transform'; then
    mkdir -p "$tmp/traversal-release"
    printf 'escape\n' > "$tmp/escape"
    (cd "$tmp" && tar -czf "$tmp/traversal-release/$(basename -- "$archive")" --transform='s|^escape$|../escape|' escape)
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$tmp/traversal-release" && sha256sum "$(basename -- "$archive")") > "$tmp/traversal-release/$(basename -- "$checksum")"
    else
        (cd "$tmp/traversal-release" && shasum -a 256 "$(basename -- "$archive")") > "$tmp/traversal-release/$(basename -- "$checksum")"
    fi
    set +e
    ENCORE_HOME="$tmp/traversal-home" ENCORE_VERSION="$package_version" ENCORE_RELEASE_BASE_URL="file://$tmp/traversal-release" \
        "$repo_root/install.sh" > "$tmp/traversal.log" 2>&1
    traversal_code=$?
    set -e
    test "$traversal_code" -ne 0
    grep -q "unsafe path" "$tmp/traversal.log"
    test ! -e "$tmp/traversal-home"
fi

mkdir -p "$tmp/link-release/content/encore-$package_version-test/bin"
ln -s /tmp "$tmp/link-release/content/encore-$package_version-test/lib"
(cd "$tmp/link-release/content" && tar -czf "$tmp/link-release/$(basename -- "$archive")" .)
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$tmp/link-release" && sha256sum "$(basename -- "$archive")") > "$tmp/link-release/$(basename -- "$checksum")"
else
    (cd "$tmp/link-release" && shasum -a 256 "$(basename -- "$archive")") > "$tmp/link-release/$(basename -- "$checksum")"
fi
set +e
ENCORE_HOME="$tmp/link-home" ENCORE_VERSION="$package_version" ENCORE_RELEASE_BASE_URL="file://$tmp/link-release" \
    "$repo_root/install.sh" > "$tmp/link-archive.log" 2>&1
link_archive_code=$?
set -e
test "$link_archive_code" -ne 0
grep -q "links or special files" "$tmp/link-archive.log"
test ! -e "$tmp/link-home"

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

set +e
unsafe_output=$(ENCORE_HOME=/ "$repo_root/install.sh" --uninstall 2>&1)
unsafe_code=$?
set -e
test "$unsafe_code" -ne 0
printf '%s\n' "$unsafe_output" | grep -q "Refusing unsafe Encore install directory"

mkdir -p "$tmp/unsafe/child"
set +e
ENCORE_HOME="$tmp/unsafe/child/.." "$repo_root/install.sh" --uninstall > "$tmp/unsafe.log" 2>&1
unsafe_code=$?
set -e
test "$unsafe_code" -ne 0
test -d "$tmp/unsafe"

"$repo_root/install.sh" --install-dir "$tmp/home-v-prefix" --uninstall
test ! -e "$tmp/home-v-prefix"

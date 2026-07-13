#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: verify-release-set.sh <release-directory>" >&2
    exit 2
fi

release_dir=$(CDPATH= cd -- "$1" && pwd)
triples='x86_64-unknown-linux-gnu
aarch64-unknown-linux-gnu
x86_64-apple-darwin
aarch64-apple-darwin'
expected=$(mktemp)
actual=$(mktemp)
checksums=$(mktemp)
trap 'rm -f "$expected" "$actual" "$checksums"' EXIT HUP INT TERM

hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{ print $1 }'
    else
        shasum -a 256 "$1" | awk '{ print $1 }'
    fi
}

for triple in $triples; do
    extension=tar.gz
    archive="encore-${triple}.${extension}"
    printf '%s\n%s\n' "$archive" "$archive.sha256" >> "$expected"
done
LC_ALL=C sort -o "$expected" "$expected"

find "$release_dir" -mindepth 1 -maxdepth 1 \
    ! -name SHA256SUMS -printf '%f\n' | LC_ALL=C sort > "$actual"
if ! diff -u "$expected" "$actual"; then
    echo "Release directory does not contain the exact platform artifact set" >&2
    exit 1
fi

for triple in $triples; do
    extension=tar.gz
    archive="encore-${triple}.${extension}"
    sidecar="$release_dir/$archive.sha256"

    set -- $(awk 'NF { print $1, $2 }' "$sidecar")
    if [ "$#" -ne 2 ]; then
        echo "Invalid checksum file: $archive.sha256" >&2
        exit 1
    fi
    recorded_hash=$(printf '%s' "$1" | tr 'A-F' 'a-f')
    recorded_file=${2#\*}
    if [ "$(basename -- "$recorded_file")" != "$archive" ]; then
        echo "Checksum file names the wrong archive: $archive.sha256" >&2
        exit 1
    fi
    actual_hash=$(hash_file "$release_dir/$archive")
    if [ "$recorded_hash" != "$actual_hash" ]; then
        echo "Checksum mismatch: $archive" >&2
        exit 1
    fi
    printf '%s  %s\n' "$actual_hash" "$archive" >> "$checksums"
done

LC_ALL=C sort "$checksums" > "$release_dir/SHA256SUMS"
printf 'Verified %s release archives\n' "$(printf '%s\n' $triples | wc -l | tr -d ' ')"

#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
verifier="$repo_root/scripts/verify-release-set.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

hash_sidecar() {
    file=$1
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$(dirname -- "$file")" && sha256sum "$(basename -- "$file")") > "$file.sha256"
    else
        (cd "$(dirname -- "$file")" && shasum -a 256 "$(basename -- "$file")") > "$file.sha256"
    fi
}

for triple in \
    x86_64-unknown-linux-gnu \
    aarch64-unknown-linux-gnu \
    x86_64-apple-darwin \
    aarch64-apple-darwin
do
    file="$tmp/encore-${triple}.tar.gz"
    printf '%s\n' "$triple" > "$file"
    hash_sidecar "$file"
done
for triple in x86_64-pc-windows-msvc aarch64-pc-windows-msvc; do
    file="$tmp/encore-${triple}.zip"
    printf '%s\n' "$triple" > "$file"
    hash_sidecar "$file"
done

"$verifier" "$tmp"
test "$(wc -l < "$tmp/SHA256SUMS" | tr -d ' ')" = 6

mv "$tmp/encore-aarch64-apple-darwin.tar.gz.sha256" "$tmp/missing"
if "$verifier" "$tmp" >/dev/null 2>&1; then
    echo "Verifier accepted a missing checksum" >&2
    exit 1
fi
mv "$tmp/missing" "$tmp/encore-aarch64-apple-darwin.tar.gz.sha256"

printf 'corrupt\n' >> "$tmp/encore-x86_64-unknown-linux-gnu.tar.gz"
if "$verifier" "$tmp" >/dev/null 2>&1; then
    echo "Verifier accepted a corrupt archive" >&2
    exit 1
fi
hash_sidecar "$tmp/encore-x86_64-unknown-linux-gnu.tar.gz"

touch "$tmp/unexpected"
if "$verifier" "$tmp" >/dev/null 2>&1; then
    echo "Verifier accepted an unexpected artifact" >&2
    exit 1
fi

printf 'Release set verification tests passed\n'

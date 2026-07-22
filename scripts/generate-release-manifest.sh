#!/usr/bin/env sh
set -eu

if [ "$#" -ne 6 ]; then
    echo "usage: generate-release-manifest.sh <release-dir> <version> <tag> <commit> <repository> <output-name>" >&2
    exit 2
fi

release_dir=$1
version=${2#v}
tag=$3
commit=$4
repository=$5
output_name=$6
channel=$("$(dirname -- "$0")/release-channel.sh" "$version")
output="$release_dir/$output_name"

case "$tag$commit$repository$output_name" in
    *'"'*|*'\\'*) echo "release manifest metadata contains unsafe characters" >&2; exit 1 ;;
esac

printf '{"schema":1,"channel":"%s","version":"%s","tag":"%s","commit":"%s","assets":[' \
    "$channel" "$version" "$tag" "$commit" > "$output"
separator=
for triple in \
    x86_64-unknown-linux-gnu \
    aarch64-unknown-linux-gnu \
    x86_64-apple-darwin \
    aarch64-apple-darwin \
    x86_64-pc-windows-msvc
do
    case "$triple" in
        *-windows-*) extension=zip; format=zip ;;
        *) extension=tar.gz; format=tar.gz ;;
    esac
    asset="encore-$triple.$extension"
    test -s "$release_dir/$asset"
    test -s "$release_dir/$asset.sha256"
    checksum=$(awk 'NF {print tolower($1); exit}' "$release_dir/$asset.sha256")
    case "$checksum" in
        ''|*[!0-9a-f]*) echo "invalid checksum for $asset" >&2; exit 1 ;;
    esac
    test "$(printf '%s' "$checksum" | wc -c | tr -d ' ')" = 64
    printf '%s{"triple":"%s","url":"https://github.com/%s/releases/download/%s/%s","sha256":"%s","format":"%s"}' \
        "$separator" "$triple" "$repository" "$tag" "$asset" "$checksum" "$format" >> "$output"
    separator=,
done
printf ']}\n' >> "$output"
printf '%s\n' "$output"

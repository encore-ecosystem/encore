#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
temporary=$(mktemp -d "${TMPDIR:-/tmp}/encore-release-channels.XXXXXX")
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

for triple in \
    x86_64-unknown-linux-gnu \
    aarch64-unknown-linux-gnu \
    x86_64-apple-darwin \
    aarch64-apple-darwin
do
    printf '%s\n' "$triple" > "$temporary/encore-$triple.tar.gz"
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$temporary" && sha256sum "encore-$triple.tar.gz") > "$temporary/encore-$triple.tar.gz.sha256"
    else
        (cd "$temporary" && shasum -a 256 "encore-$triple.tar.gz") > "$temporary/encore-$triple.tar.gz.sha256"
    fi
done
printf 'windows\n' > "$temporary/encore-x86_64-pc-windows-msvc.zip"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$temporary" && sha256sum encore-x86_64-pc-windows-msvc.zip) > "$temporary/encore-x86_64-pc-windows-msvc.zip.sha256"
else
    (cd "$temporary" && shasum -a 256 encore-x86_64-pc-windows-msvc.zip) > "$temporary/encore-x86_64-pc-windows-msvc.zip.sha256"
fi

test "$("$repo_root/scripts/release-channel.sh" 1.2.3)" = stable
test "$("$repo_root/scripts/release-channel.sh" 1.2.3-beta.4)" = beta
test "$("$repo_root/scripts/release-channel.sh" 1.2.3-nightly.20260722)" = nightly
set +e
"$repo_root/scripts/release-channel.sh" 1.2.3-alpha.1 >/dev/null 2>&1
unknown_code=$?
set -e
test "$unknown_code" -ne 0

manifest=$($repo_root/scripts/generate-release-manifest.sh \
    "$temporary" 1.2.3 v1.2.3 0123456789abcdef encore-language/encore channel.json)
test "$manifest" = "$temporary/channel.json"
grep -q '"schema":1' "$manifest"
grep -q '"channel":"stable"' "$manifest"
grep -q '"version":"1.2.3"' "$manifest"
grep -q '"commit":"0123456789abcdef"' "$manifest"
test "$(grep -o '"triple"' "$manifest" | wc -l | tr -d ' ')" = 5
grep -q '"format":"zip"' "$manifest"
grep -q 'releases/download/v1.2.3/encore-x86_64-unknown-linux-gnu.tar.gz' "$manifest"

echo "Stable, beta, nightly classification and release manifest: ok"

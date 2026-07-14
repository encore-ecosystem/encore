#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: generate-pkgbuild.sh <major.minor.patch> <release-directory>" >&2
    exit 2
fi

version=$1
release_dir=$2
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || {
    echo "Version must use MAJOR.MINOR.PATCH" >&2
    exit 2
}
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
release_dir=$(CDPATH= cd -- "$release_dir" && pwd)
x86_archive="$release_dir/encore-x86_64-unknown-linux-gnu.tar.gz"
arm_archive="$release_dir/encore-aarch64-unknown-linux-gnu.tar.gz"
test -f "$x86_archive"
test -f "$arm_archive"
x86_hash=$(sha256sum "$x86_archive" | awk '{print $1}')
arm_hash=$(sha256sum "$arm_archive" | awk '{print $1}')

sed \
    -e "s/^pkgver=.*/pkgver=$version/" \
    -e "s/@X86_64_SHA256@/$x86_hash/" \
    -e "s/@AARCH64_SHA256@/$arm_hash/" \
    "$repo_root/packaging/PKGBUILD.template" > "$release_dir/PKGBUILD"

grep -Fq "sha256sums_x86_64=(\"$x86_hash\")" "$release_dir/PKGBUILD"
grep -Fq "sha256sums_aarch64=(\"$arm_hash\")" "$release_dir/PKGBUILD"
if grep -Eq 'SKIP|@[A-Z0-9_]+@' "$release_dir/PKGBUILD"; then
    echo "Generated PKGBUILD contains an unresolved or insecure checksum" >&2
    exit 1
fi
bash -n "$release_dir/PKGBUILD"
printf '%s\n' "$release_dir/PKGBUILD"

#!/usr/bin/env sh
set -eu

if [ "$#" -ne 4 ]; then
    echo "usage: package-release.sh <compiler> <target-triple> <version> <output-dir>" >&2
    exit 2
fi

compiler=$1
triple=$2
version=$3
output_dir=$4
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)
package_name="encore-${version}-${triple}"
work_dir="${output_dir}/.package-${triple}"
stage="${work_dir}/${package_name}"

rm -rf "$work_dir"
mkdir -p "$stage/bin" "$stage/lib/encore" "$stage/share/doc/encore"
case "$triple" in
    *-windows-*) binary_name=encore.exe ;;
    *) binary_name=encore ;;
esac
cp "$compiler" "$stage/bin/$binary_name"
chmod +x "$stage/bin/$binary_name" 2>/dev/null || true
cp -R "$repo_root/core" "$stage/lib/encore/core"
cp -R "$repo_root/index" "$stage/lib/encore/index"
find "$stage/lib/encore" -type d \( -name target -o -name .venv -o -name __pycache__ \) -prune -exec rm -rf '{}' +
cp "$repo_root/LICENSE" "$stage/share/doc/encore/LICENSE"
cp "$repo_root/README.md" "$stage/share/doc/encore/README.md"
printf '%s\n' "$version" > "$stage/VERSION"

if [ "$binary_name" = "encore.exe" ]; then
    archive="${output_dir}/encore-${triple}.zip"
    rm -f "$archive"
    (cd "$work_dir" && tar -a -cf "$archive" "$package_name")
else
    archive="${output_dir}/encore-${triple}.tar.gz"
    rm -f "$archive"
    tar -C "$work_dir" -czf "$archive" "$package_name"
fi
rm -rf "$work_dir"
printf '%s\n' "$archive"

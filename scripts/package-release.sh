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
test -s "$compiler"
cp "$compiler" "$stage/bin/$binary_name"
chmod +x "$stage/bin/$binary_name" 2>/dev/null || true
mkdir -p "$stage/lib/encore/index"
# Ship only the compiler's offline dependency closure. Public packages are
# resolved through the registry and must not inflate every toolchain archive.
for package in \
    core \
    std \
    rich \
    json \
    ehir \
    ehir-llvm-backend \
    toml \
    colorterm \
    log \
    llvm
do
    test -f "$repo_root/index/$package/encore.toml"
    cp -R "$repo_root/index/$package" "$stage/lib/encore/index/$package"
done
cp "$repo_root/encore.toml" "$repo_root/encore.lock" "$stage/lib/encore/"
cp -R "$repo_root/src" "$repo_root/tests" "$stage/lib/encore/"
find "$stage/lib/encore" -type d \( \( -name target ! -path '*/src/target' \) -o -name .venv -o -name __pycache__ \) -prune -exec rm -rf '{}' +
cp "$repo_root/LICENSE" "$stage/share/doc/encore/LICENSE"
cp "$repo_root/README.md" "$stage/share/doc/encore/README.md"
printf '%s\n' "$version" > "$stage/VERSION"

# Keep package metadata stable across clean checkouts and CI runners.
find "$stage" -exec touch -t 200001010000.00 '{}' +

if [ "$binary_name" = "encore.exe" ]; then
    archive="${output_dir}/encore-${triple}.zip"
    rm -f "$archive"
    (cd "$work_dir" && COPYFILE_DISABLE=1 tar -a -cf "$archive" "$package_name")
else
    archive="${output_dir}/encore-${triple}.tar.gz"
    rm -f "$archive"
    if tar --version 2>/dev/null | grep -q GNU; then
        tar -C "$work_dir" --sort=name --owner=0 --group=0 --numeric-owner -czf "$archive" "$package_name"
    else
        plain_archive="${work_dir}/package.tar"
        (cd "$work_dir" && find "$package_name" -print | LC_ALL=C sort | COPYFILE_DISABLE=1 tar --no-recursion --uid 0 --gid 0 --uname root --gname root -cf "$plain_archive" -T -)
        gzip -n -c "$plain_archive" > "$archive"
        rm -f "$plain_archive"
    fi
fi
rm -rf "$work_dir"
printf '%s\n' "$archive"

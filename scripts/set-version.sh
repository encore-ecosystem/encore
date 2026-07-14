#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: set-version.sh <major.minor.patch>" >&2
    exit 2
fi

version=$1
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || {
    echo "Version must use MAJOR.MINOR.PATCH" >&2
    exit 2
}
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no)" ]; then
    echo "Refusing to change version in a dirty tracked worktree" >&2
    exit 1
fi
old=$(cat "$repo_root/VERSION")
if [ "$old" = "$version" ]; then
    echo "Encore is already at version $version"
    exit 0
fi

replace() {
    file=$1
    expression=$2
    tmp="${file}.tmp"
    sed "$expression" "$file" > "$tmp"
    mv "$tmp" "$file"
}

printf '%s\n' "$version" > "$repo_root/VERSION"
replace "$repo_root/src/main.enq" "s/encore $old/encore $version/"
replace "$repo_root/encore.toml" "s/^version = \"$old\"/version = \"$version\"/"
replace "$repo_root/packaging/PKGBUILD.template" "s/^pkgver=$old/pkgver=$version/"
replace "$repo_root/README.md" "s/current development line is \`$old\`/current development line is \`$version\`/"
"$repo_root/scripts/verify-version.sh"
printf 'Updated Encore version: %s -> %s\n' "$old" "$version"

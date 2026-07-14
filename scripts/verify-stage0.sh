#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
bootstrap="$repo_root/bootstrap"
archive="$bootstrap/encore-stage0-linux-x86_64.gz"
provenance="$bootstrap/encore-stage0-linux-x86_64.provenance"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

(cd "$repo_root" && sha256sum --check bootstrap/encore-stage0-linux-x86_64.sha256)
gzip -t "$archive"
gzip -dc "$archive" > "$tmp/encore-stage0-linux-x86_64"
(cd "$tmp" && sha256sum --check "$bootstrap/encore-stage0-linux-x86_64.binary.sha256")

version=$(sed -n 's/^version=//p' "$provenance")
source_commit=$(sed -n 's/^source_commit=//p' "$provenance")
target=$(sed -n 's/^build_target=//p' "$provenance")
test -n "$version"
printf '%s\n' "$source_commit" | grep -Eq '^[0-9a-f]{40}$'
test "$target" = "x86_64-unknown-linux-gnu"
if git -C "$repo_root" rev-parse --git-dir >/dev/null 2>&1; then
    git -C "$repo_root" cat-file -e "$source_commit^{commit}"
fi

case "$(uname -s):$(uname -m)" in
    Linux:x86_64|Linux:amd64)
        chmod +x "$tmp/encore-stage0-linux-x86_64"
        actual=$($tmp/encore-stage0-linux-x86_64 --version)
        test "$actual" = "encore $version"
        ;;
esac

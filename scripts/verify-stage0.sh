#!/usr/bin/env sh
set -eu

release=false
if [ "${1:-}" = "--release" ]; then
    release=true
    shift
fi
if [ "$#" -ne 0 ]; then
    echo "usage: verify-stage0.sh [--release]" >&2
    exit 2
fi

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
source_dirty=$(sed -n 's/^source_dirty=//p' "$provenance")
if [ -z "$source_dirty" ]; then source_dirty=false; fi
test -n "$version"
printf '%s\n' "$source_commit" | grep -Eq '^[0-9a-f]{40}$'
test "$target" = "x86_64-unknown-linux-gnu"
case "$source_dirty" in true|false) ;; *) echo "invalid source_dirty provenance value" >&2; exit 1 ;; esac
if [ "$release" = true ] && [ "$source_dirty" = true ]; then
    echo "release stage0 provenance was generated from a dirty source tree" >&2
    exit 1
fi
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

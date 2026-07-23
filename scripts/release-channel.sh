#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: release-channel.sh <version>" >&2
    exit 2
fi

version=${1#v}
if printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    printf 'stable\n'
elif printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$'; then
    printf 'beta\n'
elif printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+-nightly\.[0-9]{8}$'; then
    printf 'nightly\n'
else
    echo "unsupported Encore release channel version: $version" >&2
    exit 1
fi

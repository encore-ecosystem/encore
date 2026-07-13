#!/usr/bin/env sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: verify-self-host.sh <seed-compiler> <compiler-project> <host-triple>" >&2
    exit 2
fi

seed_dir=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)
seed="$seed_dir/$(basename -- "$1")"
project=$(CDPATH= cd -- "$2" && pwd)
triple=$3
generated="$project/target/$triple/debug/encore"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM

(cd "$project" && "$seed" build --profile debug --target "$triple")
test -x "$generated"
cp "$generated" "$tmp/generation-1"
cp "$tmp/generation-1" "$seed"

(cd "$project" && "$seed" build --profile debug --target "$triple")
test -x "$generated"
cp "$generated" "$tmp/generation-2"

if ! cmp "$tmp/generation-1" "$tmp/generation-2"; then
    echo "Native compiler did not reach a byte-identical self-host fixed point" >&2
    exit 1
fi

cp "$tmp/generation-2" "$seed"
"$seed" --version
printf 'Verified byte-identical native self-host fixed point\n'

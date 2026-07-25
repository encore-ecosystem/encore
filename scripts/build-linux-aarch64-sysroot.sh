#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 ]]; then
  echo "usage: build-linux-aarch64-sysroot.sh OUTPUT_DIR" >&2
  exit 2
fi

output=$1
script_dir=$(cd "$(dirname "$0")" && pwd)
sudo_cmd=()
if [[ $(id -u) != 0 ]]; then sudo_cmd=(sudo); fi

"${sudo_cmd[@]}" dpkg --add-architecture arm64
if ! grep -q '^Architectures: amd64$' /etc/apt/sources.list.d/ubuntu.sources; then
  "${sudo_cmd[@]}" sed -i '/^Types: deb$/a Architectures: amd64' \
    /etc/apt/sources.list.d/ubuntu.sources
fi
"${sudo_cmd[@]}" install -m 0644 "$script_dir/ubuntu-arm64.sources" \
  /etc/apt/sources.list.d/encore-arm64.sources
"${sudo_cmd[@]}" apt-get update -qq
"${sudo_cmd[@]}" apt-get install -y --no-install-recommends \
  libc6-dev-arm64-cross \
  linux-libc-dev-arm64-cross \
  libgcc-13-dev-arm64-cross \
  libssl-dev:arm64

mkdir -p \
  "$output" \
  "$output/usr/include" \
  "$output/usr/aarch64-linux-gnu" \
  "$output/usr/lib/gcc/aarch64-linux-gnu" \
  "$output/usr/lib/aarch64-linux-gnu" \
  "$output/lib/aarch64-linux-gnu"
cp -RL /usr/aarch64-linux-gnu/. "$output/"
# Ubuntu's cross-libc linker scripts intentionally use this absolute prefix.
# LLD interprets it inside --sysroot, so preserve the canonical directory too.
cp -RL /usr/aarch64-linux-gnu/. "$output/usr/aarch64-linux-gnu/"
cp -RL /usr/include/openssl "$output/usr/include/"
if [[ -d /usr/include/aarch64-linux-gnu ]]; then
  mkdir -p "$output/usr/include/aarch64-linux-gnu"
  cp -RL /usr/include/aarch64-linux-gnu/. "$output/usr/include/aarch64-linux-gnu/"
fi
cp -RL /usr/lib/aarch64-linux-gnu/. "$output/usr/lib/aarch64-linux-gnu/"
cp -RL /usr/lib/gcc-cross/aarch64-linux-gnu/. "$output/usr/lib/gcc/aarch64-linux-gnu/"
cp -RL /lib/aarch64-linux-gnu/. "$output/lib/aarch64-linux-gnu/"

test -f "$output/include/stdio.h"
test -e "$output/lib/crt1.o"
find "$output/usr/lib/gcc/aarch64-linux-gnu" -mindepth 2 -maxdepth 2 \
  -name crtbeginS.o -type f | grep -q .
test -e "$output/usr/lib/aarch64-linux-gnu/libssl.so"
test -e "$output/usr/lib/aarch64-linux-gnu/libcrypto.so"

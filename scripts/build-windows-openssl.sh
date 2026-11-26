#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 2 ]] || { echo 'usage: build-windows-openssl.sh TARGET OUTPUT_DIRECTORY' >&2; exit 2; }
target=$1
mkdir -p "$2"
output=$(cd "$2" && pwd)
version=3.5.9
checksum=603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a
archive="openssl-$version.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
if [[ -n "${OPENSSL_SOURCE_ARCHIVE:-}" ]]; then
  cp "$OPENSSL_SOURCE_ARCHIVE" "$work/$archive"
else
  curl -fsSL --retry 2 "https://github.com/openssl/openssl/releases/download/openssl-$version/$archive" -o "$work/$archive"
fi
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$work/$archive" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$work/$archive" | awk '{print $1}')
fi
test "$actual" = "$checksum"
mkdir "$work/source"
tar -xzf "$work/$archive" --strip-components=1 -C "$work/source"
cd "$work/source"

prefix=$output
if command -v cygpath >/dev/null 2>&1; then prefix=$(cygpath -m "$prefix"); fi
options=("--prefix=$prefix" --libdir=lib no-shared no-tests)
perl=${OPENSSL_PERL:-perl}
case "$target" in
  x86_64-pc-windows-msvc)
    "$perl" Configure VC-WIN64A "${options[@]}" no-asm
    nmake build_libs
    suffix=lib
    ;;
  x86_64-w64-windows-gnu|aarch64-w64-windows-gnu)
    if [[ -n "${CC:-}" ]]; then
      if [[ "$target" == aarch64-* ]]; then options+=(no-asm); fi
      "$perl" Configure mingw64 "${options[@]}"
    elif [[ "$target" == x86_64-* ]]; then
      "$perl" Configure mingw64 --cross-compile-prefix=x86_64-w64-mingw32- "${options[@]}"
    else
      echo "Set CC, AR and RANLIB for the AArch64 LLVM MinGW toolchain" >&2
      exit 2
    fi
    make -j "${OPENSSL_BUILD_JOBS:-4}" build_libs
    suffix=a
    ;;
  *) echo "Unsupported OpenSSL target: $target" >&2; exit 2 ;;
esac
mkdir -p "$output/include" "$output/lib"
cp -R include/openssl "$output/include/"
cp "libssl.$suffix" "libcrypto.$suffix" "$output/lib/"
cp LICENSE.txt "$output/"

#!/usr/bin/env bash
set -euo pipefail

[[ $# -le 1 ]] || { echo 'usage: ci-prepare-toolchain.sh [TARGET_TRIPLE]' >&2; exit 2; }
triple=${1:-}
if [[ "$triple" == *-linux-gnu ]]; then
  sudo apt-get update
  sudo apt-get install -y libssl-dev libc-ares-dev lld
fi
if [[ "$triple" == *-w64-windows-gnu ]]; then
  version=20260616
  case "$triple" in
    x86_64-w64-windows-gnu)
      arch=x86_64
      checksum=b9b68a4d276e16fa25802aaba458e4638f64b3884c290aaccdc2d87083b6ca35
      ;;
    aarch64-w64-windows-gnu)
      arch=aarch64
      checksum=312593669435bd0bfc1a43ac3fba23c8b27e0610bade88b2738e5a01702a99ba
      ;;
    *) echo "Unsupported Windows GNU target: $triple" >&2; exit 2 ;;
  esac
  archive="llvm-mingw-$version-ucrt-$arch.zip"
  curl -fsSL --retry 2 \
    "https://github.com/mstorsjo/llvm-mingw/releases/download/$version/$archive" \
    -o "target/$archive"
  test "$(sha256sum "target/$archive" | awk '{print $1}')" = "$checksum"
  mkdir -p target/llvm-mingw-host
  unzip -q "target/$archive" -d target/llvm-mingw-host
  root=$(find target/llvm-mingw-host -mindepth 1 -maxdepth 1 -type d | head -n 1)
  test -x "$root/bin/clang.exe"
  export ENCORE_CC="$PWD/$root/bin/clang.exe"
  printf 'ENCORE_CC=%s\n' "$ENCORE_CC" >> "${GITHUB_ENV:?GITHUB_ENV is required}"
  export ENCORE_LINKER="$PWD/$root/bin/clang.exe"
  printf 'ENCORE_LINKER=%s\n' "$ENCORE_LINKER" >> "$GITHUB_ENV"
  export ENCORE_AR="$PWD/$root/bin/llvm-ar.exe"
fi

# Package archives require LLVM's archiver even when the seed used only Clang.
# Validate it before spending time on bootstrap or convergence. Do not replace
# an explicitly selected cross toolchain with the host's tools.
archiver=${ENCORE_AR:-}
if [[ -z "$archiver" ]]; then
  if command -v llvm-ar >/dev/null 2>&1; then
    archiver=$(command -v llvm-ar)
  else
    case "$(uname -s)" in
      Linux)
        for candidate in /usr/bin/llvm-ar-[0-9]*; do
          if [[ -x "$candidate" ]]; then archiver=$candidate; fi
        done
        if [[ -z "$archiver" ]]; then
          sudo apt-get update
          sudo apt-get install -y llvm
          archiver=$(command -v llvm-ar)
        fi
        ;;
      Darwin)
        prefix="$(brew --prefix)/opt/llvm"
        if [[ ! -x "$prefix/bin/llvm-ar" ]]; then brew install llvm; fi
        archiver="$prefix/bin/llvm-ar"
        ;;
      *) echo 'LLVM archiver is required; set ENCORE_AR or install LLVM' >&2; exit 1 ;;
    esac
  fi
fi
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) archiver=$(cygpath -m "$archiver") ;;
esac
"$archiver" --version
printf 'ENCORE_AR=%s\n' "$archiver" >> "${GITHUB_ENV:?GITHUB_ENV is required}"

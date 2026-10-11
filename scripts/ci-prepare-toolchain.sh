#!/usr/bin/env bash
set -euo pipefail

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
"$archiver" --version
printf 'ENCORE_AR=%s\n' "$archiver" >> "${GITHUB_ENV:?GITHUB_ENV is required}"

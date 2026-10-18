#!/usr/bin/env bash
set -euo pipefail

seed=${1:?seed compiler required}
seed_tag=${2:?published seed tag required}
shift 2

# The pre-reflection seed cannot lower typed codecs or the new async std APIs.
# Bootstrap compiler code against the libraries from that exact published tag.
# Stage2 and stage3 always use the unmodified checkout and isolated caches.
case "$seed_tag" in
  v0.1.[0-5]-neumann) ;;
  *) exec "$seed" "$@" ;;
esac
if [[ ! -f packages/core/src/reflect/mod.enq ]]; then
  exec "$seed" "$@"
fi

repository=$PWD
source_root="$repository/target/seed-source"
test ! -e "$source_root"
test ! -e target/extreme
git rev-parse --verify "$seed_tag^{commit}" >/dev/null
mkdir -p "$source_root"
tar -cf - --exclude='packages/*/target' --exclude=.git \
  src packages runtime runtime.c encore.toml VERSION README.md |
  tar -xf - -C "$source_root"
for package in core platform std json; do
  rm -rf "$source_root/packages/$package"
done
git -C "$(git rev-parse --show-toplevel)" archive "$seed_tag" packages/core packages/platform packages/std packages/json |
  tar -xf - -C "$source_root"
core_root="$source_root/packages/core"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) core_root=$(cygpath -m "$core_root") ;;
esac
(cd "$source_root" && ENCORE_CORE_DIR="$core_root" "$seed" "$@")
mv "$source_root/target/extreme" "$repository/target/extreme"

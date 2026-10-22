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
compatibility_patch="$(cd "$(dirname "$0")" && pwd)/bootstrap-path-division.patch"
if [[ -f src/modes/cache_policy.enq ]]; then
  # The published seed has Div in its std sources but only lowers numeric `/`.
  # Build a compiler from its own tagged sources with that operator backported,
  # then use it for the ordinary pre-reflection bootstrap below. Current source
  # keeps Path / component syntax throughout; no application source is rewritten.
  bridge_root="$repository/target/seed-bridge-source"
  test ! -e "$bridge_root"
  mkdir -p "$bridge_root"
  git archive "$seed_tag" src packages runtime runtime.c encore.toml VERSION README.md |
    tar -xf - -C "$bridge_root"
  git apply --directory=target/seed-bridge-source "$compatibility_patch"
  bridge_args=(build --profile extreme)
  if [[ -n "${CI_BUILD_JOBS:-}" ]]; then bridge_args+=(--jobs "$CI_BUILD_JOBS"); fi
  bridge_core="$bridge_root/packages/core"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) bridge_core=$(cygpath -m "$bridge_core") ;;
  esac
  echo "Build the published seed's Path division bridge"
  (cd "$bridge_root" && ENCORE_CORE_DIR="$bridge_core" \
    ENCORE_BUILD_CACHE="$repository/target/seed-bridge-cache" "$seed" "${bridge_args[@]}")
  executable=encore
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) executable=encore.exe ;; esac
  seed="$bridge_root/target/extreme/$executable"
  test -s "$seed"
  probe_root="$bridge_root/target/path-division-probe"
  mkdir -p "$probe_root/src"
  cat > "$probe_root/encore.toml" <<'TOML'
[project]
name = "seed_path_division"
version = "0.0.0"
dependencies = ["path@../../packages/std"]
TOML
  cat > "$probe_root/src/main.enq" <<'ENCORE'
import std::path::Path
fn main() -> u32 {
    let root = Path::new("bootstrap")
    let name = "file"
    let path = root / "nested" / name
    ret if path.name().unwrap_or("") == name && root.name().unwrap_or("") == "bootstrap" && 12_u32 / 3_u32 == 4_u32 {
        0_u32
    } else {
        1_u32
    }
}
ENCORE
  ENCORE_CORE_DIR="$bridge_core" ENCORE_BUILD_CACHE="$repository/target/seed-bridge-probe-cache" \
    "$seed" build --manifest-path "$probe_root/encore.toml"
  probe_binary=seed_path_division
  [[ "$executable" != *.exe ]] || probe_binary+=.exe
  "$probe_root/target/dev/$probe_binary"
fi
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

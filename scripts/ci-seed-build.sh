#!/usr/bin/env bash
set -euo pipefail

seed=${1:?seed compiler required}
seed_tag=${2:?published seed tag required}
shift 2

# Older seeds cannot lower the new SDK's generic/ownership contracts reliably.
# Bootstrap compiler code against the libraries from that exact published tag.
# Stage2 and stage3 always use the unmodified checkout and isolated caches.
needs_path_bridge=false
case "$seed_tag" in
  v0.1.[0-5]-neumann) needs_path_bridge=true ;;
  v0.1.[6-9]-neumann|v0.1.1[0-3]-neumann|v0.1.15-neumann) ;;
  *) exec "$seed" "$@" ;;
esac
if [[ ! -f packages/core/src/reflect/mod.enq ]]; then
  exec "$seed" "$@"
fi

repository=$PWD
compatibility_patch="$(cd "$(dirname "$0")" && pwd)/bootstrap-path-division.patch"
if [[ "$needs_path_bridge" == true && -f src/modes/cache_policy.enq ]]; then
  # The published seed has Div in its std sources but only lowers numeric `/`.
  # Build a compiler from its own tagged sources with that operator backported,
  # then use it for the ordinary pre-reflection bootstrap below. Current source
  # keeps Path / component syntax throughout; no application source is rewritten.
  bridge_root="$repository/target/seed-bridge-source"
  test ! -e "$bridge_root"
  mkdir -p "$bridge_root"
  python3 "$repository/scripts/sdk_packages.py" --ref "$seed_tag" export --destination "$bridge_root" \
    --path src --path packages --path runtime --path runtime.c --path encore.toml --path VERSION --path README.md
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
# Submodule-based seeds can pin an ancestor that a shallow SDK checkout has
# not fetched. Fetch only those exact objects before exporting the seed SDK.
while read -r mode kind object path; do
  if [[ "$mode" == 160000 && -d "$repository/$path" ]]; then
    if ! git -C "$repository/$path" cat-file -e "$object^{commit}" 2>/dev/null; then
      git -C "$repository/$path" fetch origin "$object"
    fi
  fi
done < <(git ls-tree -r "$seed_tag" -- packages/core packages/platform packages/std packages/json)
mkdir -p "$source_root"
tar -cf - --exclude='packages/*/target' --exclude=.git \
  src packages runtime runtime.c encore.toml README.md |
  tar -xf - -C "$source_root"
for package in core platform std json; do
  rm -rf "$source_root/packages/$package"
done
python3 "$repository/scripts/sdk_packages.py" --ref "$seed_tag" export --destination "$source_root" \
  --path packages/core --path packages/platform --path packages/std --path packages/json
python3 "$repository/scripts/sdk_packages.py" --ref "$seed_tag" manifest --output "$repository/target/seed-sdk.json"
jq -n --arg seed "$seed_tag" --slurpfile sdk "$repository/target/seed-sdk.json" \
  '{schema:1, stage:1, sdk_source:$seed, sdk_packages:$sdk[0].packages}' > "$repository/target/seed-bootstrap.json"
# Current compiler checkpoints use four scalar codec helpers absent from older
# SDKs. Add that standalone native ABI to the isolated stage1 runtime only.
if [[ -f "$repository/packages/core/runtime_codec.h" ]] &&
   ! grep -Eq 'encore_codec_read_u32_le|#include "runtime_codec.h"' "$source_root/packages/core/runtime.c"; then
  cp "$repository/packages/core/runtime_codec.h" "$source_root/packages/core/runtime_codec.h"
  printf '\n#include "runtime_codec.h"\n' >> "$source_root/packages/core/runtime.c"
fi
core_root="$source_root/packages/core"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) core_root=$(cygpath -m "$core_root") ;;
esac
(cd "$source_root" && ENCORE_CORE_DIR="$core_root" "$seed" "$@")
mv "$source_root/target/extreme" "$repository/target/extreme"

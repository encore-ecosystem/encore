#!/usr/bin/env bash
set -euo pipefail
repository=${ENCORE_TEST_REPOSITORY:?}
export CI_PROBE_CASE=${1:?}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cd "$scratch"
case "$CI_PROBE_CASE" in
  restore-context)
    awk '/^      run: \|$/ { body=1; next } body { sub(/^        /, ""); print }' \
      "$repository/.github/actions/stage3-context/action.yml" > restore.sh
    test -s restore.sh
    export CI_TARGET=x86_64-unknown-linux-gnu CI_EXECUTABLE=encore
    export CI_SEED_TAG=v0.1.1-neumann CI_INDEX_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    for scenario in empty populated corrupt missing-sources; do
      workspace="$scratch/$scenario/encore"
      context="$workspace/target/test-context"
      mkdir -p "$context/bin" "$context/system-index/packages/core"
      cp "$repository/VERSION" "$workspace/VERSION"
      cp "$repository/tests/ci/mock-compiler.sh" "$context/bin/encore"
      cp "$repository/../encore-index/packages/core/encore.toml" "$context/system-index/packages/core/"
      digest=$(sha256sum "$context/bin/encore" | awk '{print $1}')
      release=$(tr -d '\r\n' < "$workspace/VERSION")
      jq -n --arg commit "$GITHUB_SHA" --arg release "$release" \
        --arg target "$CI_TARGET" --arg seed "$CI_SEED_TAG" --arg index "$CI_INDEX_SHA" \
        --arg digest "$digest" \
        '{schema:2, commit:$commit, release:$release, target:$target, seed:$seed,
          index_commit:$index, converged:true, stage2_sha256:$digest,
          stage3_sha256:$digest, compiler_sha256:$digest, dependencies_sha256:$digest}' \
        > "$context/provenance.json"
      export GITHUB_ENV="$workspace/environment"
      case "$scenario" in
        populated)
          mkdir -p "$context/registry/packages"
          printf 'cached package\n' > "$context/registry/packages/fixture"
          ;;
        corrupt) printf 'corrupted\n' >> "$context/bin/encore" ;;
        missing-sources) mv "$context/system-index" "$workspace/removed-sources" ;;
      esac
      if [[ "$scenario" == corrupt || "$scenario" == missing-sources ]]; then
        if (cd "$workspace" && bash "$scratch/restore.sh"); then exit 1; fi
        test ! -e "$GITHUB_ENV"
      else
        (cd "$workspace" && bash "$scratch/restore.sh")
        cmp "$context/bin/encore" "$workspace/target/stage3/encore"
        test -x "$workspace/target/stage3/encore"
        test -d "$workspace/target/registry"
        cmp "$context/system-index/packages/core/encore.toml" "$workspace/../encore-index/packages/core/encore.toml"
        grep -qx 'ENCORE_INDEX_URL=http://127.0.0.1:9/index' "$GITHUB_ENV"
        if [[ "$scenario" == populated ]]; then
          cmp "$context/registry/packages/fixture" "$workspace/target/registry/packages/fixture"
        else
          test -z "$(ls -A "$workspace/target/registry")"
        fi
      fi
    done
    ;;
  bridge-x86|bridge-arm)
    mkdir -p encore/target/dependency-download encore-index/packages/core seed
    cp "$repository/tests/ci/mock-compiler.sh" seed/encore
    chmod +x seed/encore
    cp "$repository/VERSION" encore/VERSION
    cp "$repository/../encore-index/packages/core/encore.toml" encore-index/packages/core/
    printf '%064d\n' 0 > encore/target/dependency-download/dependencies.tar.gz.sha256
    export LLVM_MINGW_ROOT="$scratch/toolchain with spaces"
    export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    export CI_PROBE_TARGET=x86_64-w64-windows-gnu
    [[ "$CI_PROBE_CASE" != bridge-arm ]] || CI_PROBE_TARGET=aarch64-w64-windows-gnu
    cd encore
    bash "$repository/scripts/ci-produce-stage1.sh" "$scratch/seed/encore" v0.1.2-neumann "$CI_PROBE_TARGET"
    test "$(tr '\n' ' ' < phases)" = 'producer cross '
    destination="target/stage1-artifacts/$CI_PROBE_TARGET"
    checksum=$(sha256sum "$destination/encore.exe" | awk '{print $1}')
    jq -e --arg target "$CI_PROBE_TARGET" --arg checksum "$checksum" \
      '.schema == 2 and .target == $target and .producer == "linux" and
       .bootstrap == null and .seed == "v0.1.2-neumann" and
       .executable == "encore.exe" and .executable_sha256 == $checksum' "$destination/manifest.json"
    if bash "$repository/scripts/ci-produce-stage1.sh" "$scratch/seed/encore" v0.1.2-neumann aarch64-unknown-linux-gnu; then exit 1; fi
    test "$(tr '\n' ' ' < phases)" = 'producer cross '
    ;;
  bootstrap|mismatch|build-failure)
    mkdir -p seed target/dependency-download
    cp "$repository/tests/ci/mock-compiler.sh" seed/encore
    chmod +x seed/encore
    printf '0.1.4-neumann\n' > VERSION
    printf '%064d\n' 0 > target/dependency-download/dependencies.tar.gz.sha256
    export SEED_COMPILER="$scratch/seed/encore" CI_TARGET=x86_64-unknown-linux-gnu CI_EXECUTABLE=encore
    export CI_SEED_TAG=v0.1.1-neumann CI_INDEX_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    unset CI_BUILD_JOBS
    if [[ "$CI_PROBE_CASE" == bootstrap ]]; then
      bash "$repository/scripts/ci-bootstrap.sh"
      test "$(tr '\n' ' ' < phases)" = 'seed stage1 stage2 '
      test -d target/bootstrap-cache-1 && test -d target/bootstrap-cache-2 && test -d target/bootstrap-cache-3
      cmp target/stage2/encore target/stage3/encore
      jq -e '.converged and .stage2_sha256 == .stage3_sha256 and .compiler_sha256 == .stage3_sha256' target/convergence.json
    else
      if bash "$repository/scripts/ci-bootstrap.sh" > failed.log 2>&1; then exit 1; fi
      if [[ "$CI_PROBE_CASE" == mismatch ]]; then
        test "$(tr '\n' ' ' < phases)" = 'seed stage1 stage2 '
      else
        test "$(tr '\n' ' ' < phases)" = 'seed stage1 '
      fi
      test ! -e target/convergence.json
    fi
    ;;
  archive)
    release=0.1.4-neumann
    for triple in x86_64-unknown-linux-gnu x86_64-pc-windows-msvc; do
      root="encore-$release-$triple"
      extension=
      asset=archive.tar.gz
      [[ "$triple" != *-windows-* ]] || { extension=.exe; asset=archive.zip; }
      mkdir -p "$root/bin"
      printf '%s\n' "$release" > "$root/VERSION"
      cp "$repository/tests/ci/mock-compiler.sh" "$root/bin/encore$extension"
      cp "$root/bin/encore$extension" "$root/bin/encore-lsp$extension"
      digest=$(sha256sum "$root/bin/encore$extension" | awk '{print $1}')
      jq -n --arg sha "$digest" '{compiler_sha256:$sha, lsp_sha256:$sha}' > provenance.json
      if [[ -n "$extension" ]]; then zip -qr "$asset" "$root"; else tar -czf "$asset" "$root"; fi
      bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" provenance.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" wrong "$asset" provenance.json; then exit 1; fi
      jq '.lsp_sha256 = "wrong"' provenance.json > invalid.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" invalid.json; then exit 1; fi
      if [[ -z "$extension" ]]; then
        tar -cf duplicate.tar "$root"
        tar -rf duplicate.tar "$root/VERSION"
        gzip duplicate.tar
        if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" duplicate.tar.gz provenance.json; then exit 1; fi
      fi
    done
    ;;
  *)
    mkdir bin
    cp "$repository/tests/ci/mock-gh.sh" bin/gh
    chmod +x bin/gh
    export PATH="$scratch/bin:$PATH"
    export GITHUB_REPOSITORY=encore-ecosystem/encore GITHUB_SHA
    GITHUB_SHA=$(git -C "$repository" rev-parse HEAD)
    export CI_PROBE_HEAD=$GITHUB_SHA
    [[ "$CI_PROBE_CASE" != merge ]] || CI_PROBE_HEAD=cccccccccccccccccccccccccccccccccccccccc
    export CI_PROBE_TREE
    CI_PROBE_TREE=$(git -C "$repository" rev-parse HEAD^{tree})
    [[ "$CI_PROBE_CASE" != changed ]] || CI_PROBE_TREE=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    export GITHUB_OUTPUT="$scratch/output"
    cd "$repository"
    if [[ "$CI_PROBE_CASE" == required ]]; then
      CI_PROBE_CASE=incomplete
      if bash scripts/select-ci-candidate.sh --required; then exit 1; fi
    else
      bash scripts/select-ci-candidate.sh
    fi
    case "$CI_PROBE_CASE" in
      exact|merge)
        grep -qx 'run_id=42' "$GITHUB_OUTPUT"
        grep -qx "source_commit=$CI_PROBE_HEAD" "$GITHUB_OUTPUT"
        grep -qx 'reused=true' "$GITHUB_OUTPUT"
        ;;
      *) grep -qx 'reused=false' "$GITHUB_OUTPUT" ;;
    esac
    ;;
esac

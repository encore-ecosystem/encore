#!/usr/bin/env bash
set -euo pipefail
repository=${ENCORE_TEST_REPOSITORY:?}
export CI_PROBE_CASE=${1:?}
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cd "$scratch"
case "$CI_PROBE_CASE" in
  seed-compat)
    mkdir -p source/src/frontend source/src/modes source/runtime \
      source/packages/{core,platform,std,json}/src seed
    for package in core platform std json; do
      printf 'seed-%s\n' "$package" > "source/packages/$package/src/lib.enq"
    done
    printf 'seed-analysis\n' > source/src/frontend/analysis_database.enq
    printf 'seed-build\n' > source/src/modes/build.enq
    touch source/runtime.c source/encore.toml source/README.md
    printf '0.1.6-neumann\n' > source/VERSION
    mkdir -p source/scripts
    cp "$repository/scripts/sdk_packages.py" source/scripts/
    git -C source init -q
    git -C source add .
    git -C source -c user.name=Fixture -c user.email=fixture@example.invalid commit -qm seed
    git -C source tag v0.1.5-neumann
    mkdir -p source/packages/core/src/reflect
    printf 'reflection\n' > source/packages/core/src/reflect/mod.enq
    printf 'typed-json\n' > source/packages/json/src/lib.enq
    printf 'configured-analysis\n' > source/src/frontend/analysis_database.enq
    mkdir -p source/src/target
    printf 'current-target\n' > source/src/target/mod.enq
    cp "$repository/tests/ci/mock-compiler.sh" seed/encore
    chmod +x seed/encore
    cd source
    ENCORE_BUILD_CACHE="$PWD/target/cache" bash "$repository/scripts/ci-seed-build.sh" \
      "$scratch/seed/encore" v0.1.5-neumann build --profile extreme
    test -s target/extreme/encore
    test "$(cat packages/json/src/lib.enq)" = typed-json
    test "$(cat src/frontend/analysis_database.enq)" = configured-analysis
    test -f packages/core/src/reflect/mod.enq
    test "$(cat target/seed-source/packages/json/src/lib.enq)" = seed-json
    test "$(cat target/seed-source/src/frontend/analysis_database.enq)" = configured-analysis
    test "$(cat target/seed-source/src/target/mod.enq)" = current-target
    test ! -e target/seed-source/packages/core/src/reflect/mod.enq
    ;;
  restore-context)
    awk '/^      run: \|$/ { body=1; next } body { sub(/^        /, ""); print }' \
      "$repository/.github/actions/stage3-context/action.yml" > restore.sh
    test -s restore.sh
    export CI_TARGET=x86_64-unknown-linux-gnu CI_EXECUTABLE=encore
    export CI_SEED_TAG=v0.1.1-neumann
    export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    for scenario in valid corrupt missing-sources wrong-commit legacy-provenance wrong-profile missing-profile wrong-sdk-digest wrong-sdk-commit missing-sdk-provenance; do
      workspace="$scratch/$scenario/encore"
      context="$workspace/target/test-context"
      mkdir -p "$(dirname "$workspace")"
      git clone --quiet --shared --no-checkout "$repository" "$workspace"
      mkdir -p "$context/bin" "$workspace/packages" "$workspace/lsp"
      mkdir -p "$workspace/scripts" "$workspace/src"
      cp "$repository/scripts/project-metadata.py" "$repository/scripts/sdk_packages.py" "$workspace/scripts/"
      while IFS= read -r package; do
        ln -s "$repository/$package" "$workspace/$package"
      done < <(git -C "$repository" ls-tree --name-only HEAD packages/)
      cp "$repository/src/version.enq" "$workspace/src/"
      cp "$repository/encore.toml" "$workspace/"
      cp "$repository/tests/ci/mock-compiler.sh" "$context/bin/encore"
      cp "$repository/lsp/encore.toml" "$workspace/lsp/"
      python3 "$workspace/scripts/sdk_packages.py" manifest --verify-checkout --output "$workspace/sdk-packages.json"
      sdk_digest=$(sha256sum "$workspace/sdk-packages.json" | awk '{print $1}')
      digest=$(sha256sum "$context/bin/encore" | awk '{print $1}')
      release=$(python3 "$workspace/scripts/project-metadata.py" --field release)
      jq -n --arg commit "$GITHUB_SHA" --arg release "$release" \
        --arg target "$CI_TARGET" --arg seed "$CI_SEED_TAG" \
        --arg digest "$digest" --arg sdk_digest "$sdk_digest" --slurpfile sdk "$workspace/sdk-packages.json" \
        '{schema:3, commit:$commit, release:$release, target:$target, seed:$seed,
          profile:"extreme", converged:true, stage2_sha256:$digest,
          stage3_sha256:$digest, compiler_sha256:$digest,
          sdk_sha256:$sdk_digest, sdk_packages:$sdk[0].packages}' \
        > "$context/provenance.json"
      export GITHUB_ENV="$workspace/environment"
      case "$scenario" in
        corrupt) printf 'corrupted\n' >> "$context/bin/encore" ;;
        missing-sources) mv "$workspace/packages" "$workspace/removed-sources" ;;
        wrong-commit)
          jq '.commit = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        wrong-profile)
          jq '.profile = "release"' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        missing-profile)
          jq 'del(.profile)' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        legacy-provenance)
          jq '.schema = 2' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        wrong-sdk-digest)
          jq '.sdk_sha256 = "wrong"' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        wrong-sdk-commit)
          jq '.sdk_packages[0].commit = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
        missing-sdk-provenance)
          jq 'del(.sdk_sha256, .sdk_packages)' "$context/provenance.json" > "$workspace/invalid.json"
          mv "$workspace/invalid.json" "$context/provenance.json"
          ;;
      esac
      if [[ "$scenario" != valid ]]; then
        if (cd "$workspace" && bash "$scratch/restore.sh"); then exit 1; fi
        test ! -e "$GITHUB_ENV"
      else
        (cd "$workspace" && bash "$scratch/restore.sh")
        cmp "$context/bin/encore" "$workspace/target/stage3/encore"
        test -x "$workspace/target/stage3/encore"
        test -d "$workspace/target/registry"
        test ! -e "$workspace/../encore-index"
        grep -qx 'ENCORE_INDEX_URL=http://127.0.0.1:9/index' "$GITHUB_ENV"
        test -z "$(ls -A "$workspace/target/registry")"
      fi
    done
    ;;
  bootstrap|mismatch|build-failure|native-windows-x86|native-windows-arm)
    mkdir -p seed
    cp "$repository/tests/ci/mock-compiler.sh" seed/encore
    chmod +x seed/encore
    mkdir -p src
    cp "$repository/encore.toml" .
    cp "$repository/src/version.enq" src/
    export CI_PROBE_RELEASE
    CI_PROBE_RELEASE=$(python3 "$repository/scripts/project-metadata.py" --field release)
    export SEED_COMPILER="$scratch/seed/encore" CI_TARGET=x86_64-unknown-linux-gnu CI_EXECUTABLE=encore
    export CI_SEED_TAG=v0.1.1-neumann
    export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    unset CI_BUILD_JOBS
    if [[ "$CI_PROBE_CASE" == native-windows-* ]]; then
      CI_TARGET=x86_64-w64-windows-gnu
      [[ "$CI_PROBE_CASE" != native-windows-arm ]] || CI_TARGET=aarch64-w64-windows-gnu
      CI_EXECUTABLE=encore.exe
      CI_SEED_TAG=v0.1.12-neumann
      export CI_BUILD_JOBS=2
      cp "$SEED_COMPILER" "$scratch/seed/encore.exe"
      SEED_COMPILER="$scratch/seed/encore.exe"
    fi
    if [[ "$CI_PROBE_CASE" == bootstrap || "$CI_PROBE_CASE" == native-windows-* ]]; then
      bash "$repository/scripts/ci-bootstrap.sh"
      test "$(tr '\n' ' ' < phases)" = 'seed stage1 stage2 '
      test -d target/bootstrap-cache-1 && test -d target/bootstrap-cache-2 && test -d target/bootstrap-cache-3
      cmp "target/stage2/$CI_EXECUTABLE" "target/stage3/$CI_EXECUTABLE"
      jq -e '.schema == 3 and .profile == "extreme" and .converged and .stage2_sha256 == .stage3_sha256 and .compiler_sha256 == .stage3_sha256 and
        (has("index_commit") | not) and (has("dependencies_sha256") | not)' target/convergence.json
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
      python3 "$repository/scripts/sdk_packages.py" export-sdk --destination "$root/lib/encore/index" --manifest "$root/SDK.json"
      sdk_digest=$(sha256sum "$root/SDK.json" | awk '{print $1}')
      digest=$(sha256sum "$root/bin/encore$extension" | awk '{print $1}')
      jq -n --arg sha "$digest" --arg sdk_digest "$sdk_digest" --slurpfile sdk "$root/SDK.json" \
        '{compiler_sha256:$sha, lsp_sha256:$sha, profile:"extreme", lsp_profile:"extreme",
          sdk_sha256:$sdk_digest, sdk_packages:$sdk[0].packages}' > provenance.json
      if [[ -n "$extension" ]]; then zip -qr "$asset" "$root"; else tar -czf "$asset" "$root"; fi
      bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" provenance.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" wrong "$asset" provenance.json; then exit 1; fi
      jq '.lsp_sha256 = "wrong"' provenance.json > invalid.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" invalid.json; then exit 1; fi
      jq '.sdk_sha256 = "wrong"' provenance.json > invalid-sdk.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" invalid-sdk.json; then exit 1; fi
      jq '.sdk_packages[0].commit = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"' provenance.json > invalid-sdk.json
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" invalid-sdk.json; then exit 1; fi
      for field in profile lsp_profile; do
        jq --arg field "$field" '.[$field] = "release"' provenance.json > invalid-profile.json
        if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" invalid-profile.json; then exit 1; fi
        jq --arg field "$field" 'del(.[$field])' provenance.json > missing-profile.json
        if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$asset" missing-profile.json; then exit 1; fi
      done
      mv "$root/lib/encore/index/serialize" missing-serialize
      if [[ -n "$extension" ]]; then zip -qr incomplete.zip "$root"; else tar -czf incomplete.tar.gz "$root"; fi
      incomplete=incomplete.tar.gz
      [[ -z "$extension" ]] || incomplete=incomplete.zip
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$incomplete" provenance.json; then exit 1; fi
      mv missing-serialize "$root/lib/encore/index/serialize"
      mv "$root/lib/encore/index/ehir-core" missing-ehir-core
      if [[ -n "$extension" ]]; then zip -qr missing-ehir-core.zip "$root"; else tar -czf missing-ehir-core.tar.gz "$root"; fi
      incomplete=missing-ehir-core.tar.gz
      [[ -z "$extension" ]] || incomplete=missing-ehir-core.zip
      if bash "$repository/scripts/verify-release-archive.sh" "$triple" "$release" "$incomplete" provenance.json; then exit 1; fi
      mv missing-ehir-core "$root/lib/encore/index/ehir-core"
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

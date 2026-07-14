# Releasing Encore

The release workflow publishes native archives for Linux and macOS on x86_64
and aarch64. Creating the final version commit and tag is a maintainer action;
GitHub Actions performs bootstrap verification, tests, packaging, checksums,
and release publication.

## Prepare

1. Start from a clean tracked worktree on the intended release commit.
2. Set the canonical version:

   ```sh
   scripts/set-version.sh 1.0.0
   ```

3. Build the native compiler and run the local release-critical checks:

   ```sh
   ./target/extreme/encore build --profile debug
   scripts/verify-version.sh target/debug/encore
   scripts/verify-stage0.sh
   scripts/verify-no-python.sh
   scripts/verify-self-host.sh target/debug/encore . x86_64-unknown-linux-gnu
   scripts/smoke-cross-target.sh target/debug/encore
   scripts/test-test-runner.sh target/debug/encore
   scripts/test-cli-contract.sh target/debug/encore
   ```

   Verify the public package index from a fresh cache:

   ```sh
   repo=$PWD
   compiler=$repo/target/debug/encore
   tmp=$(mktemp -d)
   mkdir -p "$tmp/project/src"
   printf '%s\n' \
     '[project]' \
     'name = "release_index_smoke"' \
     'version = "0.0.0"' \
     'dependencies = []' > "$tmp/project/encore.toml"
   printf 'fn main() -> u32 { ret 0_u32 }\n' > "$tmp/project/src/main.enq"
   (
     cd "$tmp/project"
     ENCORE_CORE_DIR="$repo/index/core" ENCORE_REGISTRY_CACHE="$tmp/cache" "$compiler" add rich
     ENCORE_CORE_DIR="$repo/index/core" ENCORE_REGISTRY_CACHE="$tmp/cache" "$compiler" build
   )
   rm -rf "$tmp"
   ```

   This gate requires the official index metadata and package release assets to
   remain available with their published checksums.

4. Review and commit the version changes. Regenerate stage0 only when changing
   the bootstrap trust root; commit its archive, both checksums, and provenance
   together.
5. Push the release commit and wait for Native CI to pass.
6. Run `Native Release` manually with version `1.0.0`. A workflow dispatch
   builds and verifies all artifacts but does not publish a GitHub release.

## Publish

After reviewing the dry-run artifacts, create and push the matching tag:

```sh
git tag -s v1.0.0 -m "Encore v1.0.0"
git push origin v1.0.0
```

The tag must match `VERSION`; the workflow rejects a mismatch. After it
finishes, verify that the release contains four archives, four sidecar checksum
files, `SHA256SUMS`, and the checksum-pinned `PKGBUILD`. Finally, install from
the public release and compile a project:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-language/encore/trunk/install.sh | \
  sh -s -- --version 1.0.0
encore --version
```

# Encore release pipeline

This is the operational contract for nightly, beta, and stable releases.
`PLAN.md` contains the broader v0.1.5 implementation contract.

## Candidate production

Every pull request and every `trunk` push runs the native convergence and test
matrix. Superseded pull-request runs are cancelled; trunk runs are never
cancelled.

The workflow resolves trusted inputs once:

1. Select the newest non-draft, non-prerelease stable release that contains
   every required host artifact.
2. Verify the selected release checksums.
3. Resolve `encore.lock` once on Linux.
4. Upload the package cache, metadata, lockfile, and core sources as one
   checksummed dependency bundle.

Three producer jobs build a current compiler once from the selected seed.
Linux uses that compiler to produce Linux x86-64/AArch64 and Windows GNU
x86-64/AArch64 stage1 binaries. Apple Silicon produces both Darwin binaries,
and Windows retains the native MSVC lineage.

Each target executes its downloaded stage1 natively to build stage2, then uses
stage2 to build stage3. Stage2 and stage3 must be byte-identical. The verified
stage3 compiler then runs the complete test plan through its bounded parallel
worker pool. Aggregation fails on missing, duplicate, or failed tests.

The Linux producer creates a relocatable Ubuntu AArch64 sysroot and uses the
pinned LLVM-MinGW clang/lld distribution as its cross driver. Candidate
production also emits compiler-coupled target kits for Linux AArch64 and
Windows GNU x86-64/AArch64. Promotion verifies and publishes those kit
descriptors and archives alongside the compiler binaries.

The successful trunk run stores reproducible distribution archives, checksums,
and provenance for the exact source SHA for 30 days. These are release
candidates; producing an artifact alone does not publish it.

Every stage1 has checked provenance for the source commit, version, selected
seed, dependency bundle, producer, target, and executable checksum. Native
stage2/stage3 convergence is therefore separate from cross-production while
the expensive frontend bootstrap runs only once per producer OS.

## Promotion

Pushing a version tag never compiles source. The promotion workflow requires a
successful `trunk` CI run whose `head_sha` exactly equals the tag commit,
downloads that run's `release-candidate-*` artifacts, and verifies:

- `VERSION`, `encore.toml`, and `src/version.enq` equal the tag version;
- the tag commit is contained in `origin/trunk`;
- every target provenance file names the exact tag commit and version;
- every archive matches its recorded SHA-256 checksum;
- the complete required target set is present.

If the exact candidate has expired, rerun CI for that exact commit. Promotion
has no rebuild fallback.

## Channels

- `vX.Y.Z-nightly.YYYYMMDD` promotes a nightly prerelease and updates
  `channel-nightly`.
- `vX.Y.Z-beta.N` promotes a beta prerelease and updates `channel-beta`.
- `vX.Y.Z` promotes a stable release and updates `channel-stable`.

Each immutable version release contains platform archives, per-archive
checksums, provenance, `SHA256SUMS`, and `channel.json`. A channel release is
only a mutable pointer containing the latest verified `channel.json`; compiler
self-update resolves that pointer and then downloads immutable version assets.

## Package publication

`encore publish --dry-run` runs the complete local verification and produces
the exact reproducible archive without remote changes. `encore publish` then
creates `<package>-v<version>`, uploads the immutable archive, and opens a
reviewed `encore-index` pull request.

Publication can resume only when an existing tag points to the same commit and
an existing release asset or index version has the same checksum and immutable
metadata. Any conflict aborts instead of overwriting published state.

For the 0.1.5 bootstrap transition, the compiler itself remains pinned to the
0.1.4-era package graph so the last stable compiler can build it, except for
the bootstrap-compatible `ehir_llvm_backend@0.0.1`. Publish that backend first.
After a locally verified 0.1.5 compiler exists, publish and merge the
append-only `core@0.1.0`, `platform@0.1.0`, `std@1.0.1`, and affected dependent
package versions. Only then run the protected `trunk` candidate that is
eligible for the stable 0.1.5 tag. Release candidates package the
system-library sources from the exact index commit recorded by CI, never from
a moving branch.

The index pull-request gate validates append-only ownership and archive
identity, rejects unsafe archive members, then resolves, checks, tests, and
builds every newly published package on Linux with the latest stable compiler.

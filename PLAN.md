# Encore v0.1.5 implementation plan

This document is the implementation contract for Encore v0.1.5. A requirement
is complete only when its behavior and validation described below are present.

## Goals

Encore v0.1.5 delivers:

1. A reviewed GitHub-backed package publishing workflow driven by
   `encore publish`.
2. Compiler-managed target kits and cross-compilation selected by
   `encore build --target`.
3. A platform-neutral `core`, an internal target-specific `platform`, and a
   public high-level `std`.
4. Cross-built bootstrap compilers verified to a native byte-identical
   stage2/stage3 fixed point.
5. Four-way deterministic test sharding per target with JSON and JUnit
   reporting.
6. Promotion of exact green trunk artifacts into stable, beta, and nightly
   releases without a second release rebuild.

## Package publication

### Manifest and index contract

Publishable manifests support:

```toml
[project]
name = "example"
version = "1.2.0"
repository = "https://github.com/owner/repository"
encore = ">=0.1.5, <0.2.0"

[publish]
include = []
exclude = []
```

- `repository` identifies the GitHub repository that owns release assets.
- `encore` is a SemVer requirement for compatible compiler releases.
- The resolver ignores index versions incompatible with the running compiler.
- Index metadata records the repository, source commit, source subdirectory,
  compiler requirement, immutable archive URL, and SHA-256 checksum.
- Existing index entries and published versions are append-only. Yank remains
  the only supported mutation of a published version.

### CLI workflow

The public commands are:

```sh
encore publish --dry-run
encore publish
```

Publication uses the current `gh auth` session. Before external mutation it
must verify a clean and pushed Git worktree, manifest and lockfile consistency,
dependency validity, formatting, checking, linting, tests, build success,
archive safety, and index version availability.

The archive:

- is rooted at the package directory, including packages in repository
  subdirectories;
- starts from Git-tracked files below that root;
- always excludes `.git`, `target`, and machine-local output;
- applies `.encoreignore` and `[publish].include`/`exclude`;
- always contains required manifest and source files;
- includes referenced private `workspace@` refrains;
- is reproducible and named `<package>-<version>.tar.gz`.

`--dry-run` creates and validates the exact archive and prints its metadata and
checksum without creating remote state.

Normal publication:

1. Creates and pushes annotated tag `<package>-v<version>`.
2. Creates a GitHub Release and uploads the immutable archive.
3. Creates a branch in the authenticated user's `encore-index` fork.
4. Adds or appends sparse metadata.
5. Opens a reviewed pull request to `encore-ecosystem/encore-index`.

The operation is resumable. Existing tag, release, asset, or metadata may be
reused only when commit identity and checksums match exactly; conflicting
remote state aborts without replacement. Publication is pending until the
index PR is reviewed and merged.

Index CI validates append-only history, repository ownership, archive paths,
checksums and manifest identity, compiler compatibility, dependency
resolution, and at least a Linux package build and test.

## Core, platform, and standard library

- `core` contains one target-independent implementation of language
  primitives: foundational traits, `Option`, `Result`, collections, portable
  ownership support, and portable async machinery.
- Platform APIs are removed from `core`.
- User-facing IO, filesystem, networking, process, threading, TLS, time, and
  related APIs live in `std`.
- `std` depends on `sys@core` and the target-selected `sys@platform`.
- `platform` is an internal system refrain. Application packages cannot import
  it directly.
- No abstract refrain, provider abstraction, or general dependency aliasing is
  introduced.
- Each selected target kit mounts exactly one concrete refrain under the
  canonical identity `platform`.
- The native runtime is split into a portable language runtime and
  target-specific platform sources.
- Removed `core::*` platform imports produce migration diagnostics pointing to
  the corresponding `std::*` path.
- The breaking move occurs in v0.1.5 without a deprecated compatibility layer.

## Managed target kits

Public commands:

```sh
encore target list
encore target show <triple>
encore target install <triple>
encore build --target <triple>
```

Target resolution happens before workspace loading:

```text
TargetSpec -> installed target kit -> sys@platform + toolchain + sysroot
```

A managed kit consists of:

- a host component containing compiler/linker tools executable on the host;
- a target component containing the platform refrain, runtime sources,
  headers, libraries, and sysroot.

Kit ABI is compiler-coupled. Encore 0.1.5 accepts kits from the 0.1.5 ABI line.
Kit manifests and archives are checksummed release assets. Installation is
atomic, and a completed installation supports offline builds. A missing kit
diagnostic prints the exact `encore target install` command.

Existing configuration precedence remains:

```text
CLI options > project target configuration > target-kit defaults
```

A completely configured custom target remains usable without a managed kit.
Build scripts execute with the host platform while final code generation uses
the target platform.

Managed cross-compilation is guaranteed for:

- `x86_64-unknown-linux-gnu`;
- `aarch64-unknown-linux-gnu`;
- `x86_64-w64-windows-gnu`;
- `aarch64-w64-windows-gnu`.

Native support remains for:

- `x86_64-pc-windows-msvc`;
- `x86_64-apple-darwin`;
- `aarch64-apple-darwin`.

Windows GNU is the primary Windows cross-compilation ABI. macOS is native-only
because Encore does not distribute Apple SDKs.

## Test execution and reporting

The public test CLI supports:

```sh
encore test --list --format json
encore test --shard 1/4 --report target/test-results.json
```

- Every test has a stable fully qualified ID.
- Filtering happens before sharding.
- Assignment uses a stable hash of the test ID modulo shard count.
- Shards are one-based in the CLI.
- JSON reports contain selected, passed, failed, duration, and diagnostic
  details.
- CI converts and merges reports into JUnit.
- Aggregation proves every planned test ID ran exactly once.
- A missing, duplicate, or failed test fails the target gate.
- Local execution remains sequential in v0.1.5. A generated parallel local
  harness and `--jobs` are deferred.

Every target runs four isolated test jobs from the already verified stage3
compiler and an offline dependency bundle.

## CI bootstrap

### Trusted inputs

A `resolve-inputs` job selects the latest complete stable compiler once per
workflow run. It excludes beta, nightly, channel, draft, current, and incomplete
releases; verifies release manifests and SHA-256 checksums; and records the
selected immutable tag in the job summary.

The same job creates a verified dependency bundle containing the exact
lockfile, index metadata, archives, and extracted package cache. Bootstrap and
test jobs consume this artifact offline, avoiding target-specific registry
network access.

Dynamic latest-stable selection is intentional. A rerun after a newer stable
release may select a different trusted seed, but every run records its exact
selection.

### Stage1 production

Linux uses a parallel target matrix to cross-build stage1 for:

- Linux x86-64 and AArch64;
- Windows GNU x86-64 and AArch64.

One Apple Silicon builder produces Darwin ARM64 and x86-64 stage1 artifacts.
Windows x86-64 builds the retained MSVC stage1 natively.

Every stage1 artifact includes a manifest recording source commit and version,
seed release, target triple, target-kit version, dependency-bundle checksum,
and executable checksum.

### Native convergence

Each target downloads and verifies its stage1 artifact, then:

1. Executes stage1 to build stage2.
2. Executes stage2 to build stage3.
3. Requires stage2 and stage3 compiler binaries to be byte-identical.
4. Verifies the stage3 version.
5. Uploads stage3 for test shards.

Stage1 and stage2 are not compared because stage1 was generated by the previous
compiler and may legitimately differ after code-generation changes.

PR and trunk workflows run the complete native matrix. Outdated PR runs are
cancelled; trunk runs are never cancelled by a newer push because their
artifacts can be release candidates.

## Release promotion

A successful trunk workflow packages tested stage3 binaries and all target-kit
assets with provenance, target manifests, and checksums.

The tag workflow performs no compilation. It:

1. Finds a successful protected-trunk workflow for the exact tag commit.
2. Verifies source version, target set, provenance, manifests, and checksums.
3. Downloads the exact tested artifacts.
4. Creates the GitHub release.
5. Updates the appropriate stable, beta, or nightly channel manifest.

There is no automatic rebuild fallback. If candidate artifacts expired, an
explicit candidate workflow must be rerun for the exact commit before release.

## Implementation and release gates

Implement in bootstrap-safe order:

1. Test list/shard/report support and CI aggregation.
2. Index compiler-compatibility schema and resolver filtering.
3. Target-kit parsing, installation, storage, and `sys@platform` resolution
   while the old core/runtime still works.
4. Bootstrap-compatible kits.
5. Runtime split and migration of core, std, compiler, examples, and official
   packages.
6. `encore publish --dry-run`, then resumable GitHub publishing.
7. Cross-bootstrap CI and exact-SHA release promotion.
8. Documentation and migration diagnostics.

Required verification:

- focused unit and end-to-end tests for every new CLI and failure mode;
- archive reproducibility and malicious-path tests;
- resolver compatibility and append-only metadata tests;
- host/target build-script separation;
- kit checksum, ABI mismatch, atomic install, missing-kit, and offline tests;
- four-shard exact-set aggregation on every target;
- Linux and Windows GNU cross-builds on x86-64 and AArch64;
- native Darwin and Windows MSVC builds;
- two/three-stage extreme self-host with byte-identical final stages;
- complete compiler, analyzer, formatter, CLI, integration, example, and
  release smoke suites.

## Implementation status

The v0.1.5 source implementation is complete locally. The current verification
baseline is:

- all 161 compiler tests pass exactly once across four deterministic shards;
- the merged JSON/JUnit gate reports 161 passed and zero failed;
- Windows GNU x86-64 and AArch64 outputs are valid PE32+ executables;
- a managed Linux AArch64 kit installs into an empty target directory and
  produces an AArch64 ELF executable without registry access;
- workflow YAML, shell scripts, Python tools, and both repository diffs pass
  local syntax and whitespace validation;
- index archive tests cover successful extraction, manifest identity mismatch,
  and parent-path traversal rejection.

The remaining operations are release actions rather than source
implementation: commit the reviewed changes, publish the bootstrap backend in
the documented order, merge the append-only package metadata, and run the
protected remote target matrix. They intentionally remain unperformed while
the working agreement forbids commits, branches, and speculative CI pushes.

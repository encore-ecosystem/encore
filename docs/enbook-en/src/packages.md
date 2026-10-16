# Packages And Build Scripts

Encore packages are configured by `encore.toml`.

```toml
[project]
name = "my_package"
target = "auto"
version = "0.0.0"
description = ""
readme = "README.md"
licence = "MIT"
dependencies = [
    "index@std",
]
```

## Project Fields

| Field | Meaning |
| --- | --- |
| `name` | package name |
| `target` | output kind: `auto`, `executable`, `static_lib` or `shared_lib`; legacy target triples are also accepted |
| `version` | package version string |
| `description` | package description |
| `readme` | readme path |
| `licence` | license string |
| `dependencies` | dependency references |
| `build` | optional build script path |

`core` is a system dependency injected by the compiler. Do not add `sys@core`
manually.

With `auto`, a package with `src/main.enq` builds an executable; a library-only
package with `src/lib.enq` builds a static library. When both exist, direct builds
use `main.enq`, while consumers always use the library entrypoint. An explicit
`static_lib` or `shared_lib` selects `lib.enq` even if `main.enq` also exists.
Use `encore build --target <triple>` to select the architecture independently.

Library artifacts are `lib<name>.a` (MSVC: `<name>.lib`) or `lib<name>.so`
(macOS: `lib<name>.dylib`, Windows: `<name>.dll`). Static archives include their
dependency objects and runtime support; shared libraries export linked symbols.
`--emit object`, `--emit llvm-ir`, and `--emit ehir` also accept library packages.
`encore run` and executable installation require an executable project.

## Package Compilation And Cache

For binary builds, Encore resolves a dependency graph from manifests first.
Each package is checked and compiled in its own compiler process. Workers read
their own sources; dependencies arrive as verified declarations (`.ermeta`),
generic templates (`.ertemplate`) and ordinary native archives (`.erlib`).
Generic specializations and ownership helpers are collected into one final
support unit before linking the executable.

`encore build --jobs 4` sets one shared CPU budget, not four workers per package.
Ready packages are scheduled dynamically. A dependent can start when checked
metadata is ready, without waiting for every dependency archive to finish.
Native compilation can borrow unused CPU leases. Admission also reserves RAM,
keeps 20% headroom and observes Linux container memory limits. Resource history
can raise a package's initial conservative reservation on later builds.

The content-addressed cache distinguishes three stages:

- Frontend: own sources, compiler, target, profile, features and dependency
  interfaces. An ordinary dependency-body edit does not recheck a consumer.
- Backend: frontend identity plus reachable generic-template identities. A
  template-body edit redoes backend preparation, not frontend checking.
- Native: backend identity plus selected native executables and flags. Native
  flag changes reuse the prepared package instead of rechecking its sources.

Final linking also follows dependency archives and active native-source/header
contents. A changed dependency archive is linked even when consumer code is
cached. Cache payloads are checksummed, copied into private build snapshots and
published with atomic receipts under per-key process locks. Missing or corrupt
entries are rebuilt; they do not trigger dependency-source fallback.

Package entries default to `~/.cache/encore/units-v1`; `ENCORE_BUILD_CACHE`
overrides that location. Private staging and native objects are under `target/`.
`encore build --timings` writes `encore-timings.json` in the profile output
directory, including queue time, package cache hits and total pipeline time.
These internal artifact formats are compiler-specific, not a public ABI or a
replacement for the dependency lockfile.

## Dependency References

Supported dependency references:

- `index@json`
- `workspace@ui-core`
- `path@../some-package`
- `git@https://github.com/org/repo`
- bare index names through `encore add <name>`; the command stores them as
  `index@<name>`

Use `index@` for packages published through the public index. Use `workspace@`
for a private refrain shipped inside the same distribution under
`workspace/<name>`. Use `path@` while developing two separate distributions in
one checkout, and `git@` only when intentionally following a repository outside
the official index. Relative `path@` references are resolved from the manifest
that declares them.

Every root, `path@`, `git@`, or `index@` package starts a distribution boundary.
Within that boundary, `workspace@ui-core` always resolves to
`<distribution-root>/workspace/ui-core`, including when it is declared by
another embedded refrain. An embedded refrain can depend on another embedded
refrain, but dependency cycles and duplicate refrain names are rejected.

## Dependency Commands

| Command | Behavior |
| --- | --- |
| `encore add json` | resolve `index@json`, update the manifest, and lock the complete graph |
| `encore add workspace@ui-core` | add `workspace/ui-core` from the current distribution |
| `encore add path@../json` | add a local package without copying its absolute path into the lockfile |
| `encore add git@https://github.com/org/repo` | add a Git repository dependency |
| `encore sync` | use locked index archives when present and restore missing cache entries |
| `encore sync --update` | refresh dependencies and rewrite the lockfile |
| `encore update` | equivalent dependency refresh command |

An ordinary `encore build`, `run`, or `test` does not update a locked index
dependency. Use `encore update` when you deliberately want the current package
versions from the index.

Index references may include SemVer requirements, for example
`index@json@^1.2.0`, `index@json@>=1.4.0, <2.0.0`, `index@json@1.4.*`, or
`index@json@~1.4.2`. The resolver selects exactly one version of each named
index package. It intersects direct and transitive requirements and chooses the
highest non-yanked version that satisfies the complete graph. If a later
constraint invalidates an earlier decision, the resolver backtracks and tries
the next candidate instead of retaining two versions of the package.

## Lockfile

`encore.lock` records every direct and transitive package. An index package is
identified by an immutable archive URL and SHA-256:

```toml
version = 2

[[packages]]
name = "json"
ref = "index@json"
version = "1.0.0"
archive = "https://github.com/example/json/releases/download/v1.0.0/json-1.0.0.tar.gz"
checksum = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

[[packages]]
name = "json_parser"
ref = "workspace@parser"
version = "1.0.0"
source = "embedded@json"
path = "workspace/parser"
distribution-checksum = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
```

Commit the lockfile for applications and tools. Library authors may also
commit it to make development and CI reproducible, but consumers resolve the
dependencies declared by the library's published manifest into their own root
lockfile.

The lockfile never contains the local package cache path. Deleting the cache
does not change selected versions: `encore sync` downloads the exact locked
archive and verifies the recorded checksum.

## Official Package Index

Registry metadata is obtained through a discovered API, not a GitHub metadata
repository. Package `json` is described by `/api/v1/packages/json` on the
registry origin. Set `ENCORE_DEFAULT_INDEX` to choose your default index without adding a registry
section to every project, and `ENCORE_REGISTRY_CACHE` to override
the default cache under `~/.cache/encore/registry`.

The root project can instead select one index in `encore.toml`:

```toml
[registry]
index = "https://packages.example.org/index"
```

Selection priority is `ENCORE_INDEX_URL`, the root manifest's `[registry].index`,
`ENCORE_DEFAULT_INDEX`. No built-in GitHub fallback is used. Until an official
API URL is configured, new index dependencies require an explicit registry.
Direct `git@`, `path@` and `workspace@` dependencies do not require a registry.
For local development:

```sh
export ENCORE_DEFAULT_INDEX="http://127.0.0.1:8137/index"
```

The same selection applies to resolution, publication and authentication.
Empty environment variables are treated as unset. A nonempty invalid selected
URL is an error, not a reason to try another index.
Dependencies cannot override the
root's selection, and resolution never falls back to another index. HTTPS is
required except for loopback HTTP development servers and absolute `file://`
API fixture indexes. Credentials, queries and fragments are not accepted in index
URLs. Tokens must not be stored in this field.

Newly resolved packages record `registry` in `encore.lock` and use separate cache
namespaces for each normalized index URL. After changing the index, run
`encore update` explicitly; ordinary builds and sync refuse to replace a pinned
source. Old lockfiles without `registry` retain their exact archive URLs and
checksums until an explicit update.

Resolution and publication use the selected API service. `encore publish`
discovers `/config.json` below the index URL and uploads through its same-origin
API with a keyring credential or an origin-bound CI token. A missing or
incompatible service is an error, never a fallback to GitHub.
See [registry authentication](publishing-packages.md#authentication).

An index entry contains immutable release archives in publication order:

```json
{
  "name": "json",
  "versions": [
    {
      "version": "1.0.0",
      "archive": "https://github.com/example/json/releases/download/v1.0.0/json-1.0.0.tar.gz",
      "checksum": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "yanked": false
    }
  ]
}
```

Each release archive must contain `encore.toml` at its root. Its project name
and version must match the index entry. A package may include private refrains
under `workspace/` and reference them with `workspace@`; they are part of the
same immutable archive and are not separate public index entries. Old versions
remain in the registry; withdrawn versions are marked `yanked` instead of being
removed or modified.

The v1 resolver orders entries by SemVer rather than JSON array position.
Existing lockfiles continue to use a yanked version; yanking only prevents new
resolution to that version. Ordinary `encore sync` first attempts the locked
graph. If changed manifest constraints make that graph impossible, it consults
the index and backtracks to a compatible graph; `encore update` considers all
non-yanked candidates immediately.

## Cache And Offline Builds

The default registry layout is:

```text
~/.cache/encore/registry/
└── sources/
    └── <registry-identity>/
        ├── metadata/
        ├── archives/
        └── packages/
            └── json/
                └── 1.0.0-<sha256>/
```

Metadata is needed only while adding or updating a package. A normal build
uses the package directory selected by the root lockfile. If the extracted
directory is missing but the archive remains cached, Encore verifies and
extracts it again. If both are missing, `encore sync` downloads the immutable
archive URL from the lockfile without consulting the latest index entry.

API discovery and metadata use the native HTTP client. Archive restoration
requires `curl` and `tar`.
A checksum mismatch, unsafe archive path, archive link or special file, missing
root `encore.toml`, or manifest name/version mismatch aborts resolution.

See [Publishing Packages](publishing-packages.md) for archive and API publication
requirements.

## Package Layout

Executable package:

```text
encore.toml
src/main.enq
```

Library package:

```text
encore.toml
src/lib.enq
src/module/mod.enq
```

Distribution with private refrains:

```text
encore.toml
src/lib.enq
workspace/ui-core/encore.toml
workspace/ui-core/src/lib.enq
workspace/platform-linux/encore.toml
workspace/platform-linux/src/lib.enq
```

Unit tests live next to the code they exercise and are marked with
`#attr(test)`.

`src/lib.enq` commonly re-exports modules:

```enq
pub import refrain::fmt
pub import refrain::vec
```

## Conditional Compilation

Use `#cfg(...)` to compile declarations for selected environments:

```enq
#cfg(linux)
pub fn os_name() -> str {
    ret "linux"
}

#cfg(windows)
pub fn os_name() -> str {
    ret "windows"
}
```

Pass extra flags from the CLI:

```sh
encore build --cfg linux
encore test --cfg feature=my_feature
```

## Native Build Scripts

Build scripts let packages publish native link metadata. The official `core`
package under `packages/core` in the compiler repository is the reference pattern. A build
script writes JSON to the path passed as argv `1`:

```json
{
  "native": {
    "libraries": [
      {"name": "encore_core_native", "path": "runtime.c"}
    ],
    "search_paths": [],
    "frameworks": [],
    "link_args": []
  }
}
```

Enable a build script in `encore.toml`:

```toml
[project]
name = "native_package"
target = "auto"
build = "build.enq"
dependencies = []
```

Native library entries can name a system library or a file path. Optional `cfg`
fields let metadata apply only to matching compile-time configurations.

Scripts are compiled for the host and executed with their package as the working
directory. Their optional second and third arguments contain the requested target
triple and profile. Paths in metadata are relative to the declaring package, not
the consumer or the metadata output directory. Source files are compiled once;
archives/objects are linked as files, and name-only entries select system libraries.

The compiled host script is cached, but executes on each build so changes to its
inputs are observed. Its selected sources, included headers, native files and link
arguments participate in native/link cache identities. A failed script, missing
output or malformed metadata stops the build rather than reusing stale metadata.
`encore test` also applies build scripts; `encore check` does not execute them.

## Validation Commands

Release-gate validation uses the native compiler:

```sh
./target/extreme/encore test
```

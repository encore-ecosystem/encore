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
| `target` | `auto`, `executable`, `static_lib` or `shared_lib` |
| `version` | package version string |
| `description` | package description |
| `readme` | readme path |
| `licence` | license string |
| `dependencies` | dependency references |
| `build` | optional build script path |

`core` is a system dependency injected by the compiler. Do not add `sys@core`
manually.

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

The default sparse index is
`https://raw.githubusercontent.com/encore-language/index/refs/heads/main`. Package
`json` is described by `js/json.json`; only that metadata file is downloaded.
Set `ENCORE_INDEX_URL` to use a mirror and `ENCORE_REGISTRY_CACHE` to override
the default cache under `~/.cache/encore/registry`.

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
remain in the file; withdrawn versions are marked `yanked` instead of being
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

Registry resolution requires `curl`, `tar`, and either `sha256sum` or `shasum`.
A checksum mismatch, unsafe archive path, archive link or special file, missing
root `encore.toml`, or manifest name/version mismatch aborts resolution.

See [Publishing Packages](publishing-packages.md) for archive and index PR
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

Build scripts let packages publish native link metadata. `index/core/build.enq` is the
reference pattern. It writes JSON to the path passed as argv `1`:

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

## Validation Commands

Release-gate validation uses the native compiler:

```sh
compiler="$PWD/target/extreme/encore"
for package in index/core index/ehir index/ehir-llvm-backend index/rich index/std; do
    (cd "$package" && "$compiler" test)
done
./target/extreme/encore test
```

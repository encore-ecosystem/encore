# Publishing Packages

Encore uses GitHub as package storage and
[`encore-language/index`](https://github.com/encore-language/index) as a sparse
metadata catalog. Package source can live in any public GitHub repository. A
published version is a maintainer-created `.tar.gz` asset attached to a GitHub
Release; automatically generated source archives are not used.

There is no `encore publish` command in v1. Publication is a reviewed pull
request workflow.

## Package Requirements

A publishable library contains at least:

```text
encore.toml
src/lib.enq
```

The manifest must use a lowercase package name of at least two characters.
Letters, digits, `-`, and `_` are accepted.

```toml
[project]
name = "example_math"
version = "1.0.0"
description = "Math helpers for Encore"
readme = "README.md"
licence = "MIT"
dependencies = [
    "index@std",
]
```

Before publishing:

```sh
encore sync
encore test
```

Published manifests must not contain `path@` dependencies. Replace dependencies
on separately published packages with `index@name`. A private refrain may use
`workspace@name` when its complete package is included at `workspace/name` in
the same release archive. Do not include `.git`, `target`, or machine-specific
files.

## Create A Release Archive

Create an archive whose root contains `encore.toml`, not an extra repository
directory. On a GNU tar environment:

```sh
version=1.0.0
package=example_math

tar \
  --sort=name \
  --owner=0 \
  --group=0 \
  --numeric-owner \
  --mtime='UTC 1970-01-01' \
  -czf "$package-$version.tar.gz" \
  encore.toml src workspace
```

Include `README.md`, a license file, tests, examples, and native sources when
they are part of the package. Omit `workspace` from the command when the
distribution has no private refrains. Every listed path must exist; keep
generated build output out of the archive. Archives may contain only regular
files and directories; symbolic links, hard links, and special files are
rejected.

Inspect and hash the result:

```sh
tar -tzf example_math-1.0.0.tar.gz
sha256sum example_math-1.0.0.tar.gz
```

The listing must contain `encore.toml` at the archive root and must not contain
absolute paths or `..` components.

Create a tag and upload the exact archive as a release asset:

```sh
git tag -s v1.0.0 -m "example_math v1.0.0"
git push origin v1.0.0
gh release create v1.0.0 \
  example_math-1.0.0.tar.gz \
  --title "example_math 1.0.0"
```

Never replace an uploaded asset. If an archive is wrong, publish a new package
version and a new URL.

## Add The Index Entry

Fork `encore-language/index`. Metadata paths use the first two package-name
characters:

```text
example_math -> ex/example_math.json
```

For a new package, create:

```json
{
  "name": "example_math",
  "versions": [
    {
      "version": "1.0.0",
      "archive": "https://github.com/author/example_math/releases/download/v1.0.0/example_math-1.0.0.tar.gz",
      "checksum": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "yanked": false
    }
  ]
}
```

For a new version, append an object to `versions`. Do not edit or reorder an
already published entry. Open a pull request containing only the relevant
metadata changes.

Index CI validates the path, schema, package name, SemVer, duplicate versions,
archive URL, SHA-256, archive paths, and manifest identity. Maintainers review
the package source, dependency references, licensing, and test evidence before
merging.

## Test Before Opening A PR

Push the metadata branch and point Encore to its immutable Git commit:

```sh
export ENCORE_INDEX_URL="https://raw.githubusercontent.com/<fork>/index/<commit>"
export ENCORE_REGISTRY_CACHE="$(mktemp -d)"

mkdir package-smoke
cd package-smoke
encore init --name package_smoke
encore add example_math
encore build
```

Using a fresh cache proves that metadata, download URL, checksum, archive, and
transitive dependencies work together.

## Publish An Update

1. Increase `[project].version`.
2. Run package tests.
3. Create and upload a new immutable archive.
4. Append the new version to the metadata file.
5. Open an index PR.

After merge, new projects and `encore update` select the highest compatible
SemVer version. Existing projects remain on the version recorded in
`encore.lock` unless their manifest constraints can no longer be satisfied by
that locked graph.

## Yank A Version

To prevent new selection of a broken release, open an index PR changing only:

```json
"yanked": true
```

Do not delete the metadata entry or release asset. Existing lockfiles must
remain reproducible. Publish a corrected version separately.

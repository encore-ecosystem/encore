# Publishing Packages

Encore publishes packages through a registry API, independently of where their
source repositories are hosted. Publication no longer creates GitHub releases
or pull requests in a metadata repository. Direct Git dependencies remain
available through `encore add git@https://github.com/owner/package`.

## Select a registry

Set a default once for all projects:

```sh
export ENCORE_DEFAULT_INDEX="http://127.0.0.1:8137/index"
```

A root manifest can override it:

```toml
[registry]
index = "https://packages.example.org/index"
```

The priority is `ENCORE_INDEX_URL`, the root manifest's `[registry].index`, then
`ENCORE_DEFAULT_INDEX`. Until the official API URL is configured, a new index
dependency requires an explicit registry; Encore never falls back to GitHub.
HTTPS is required except for loopback development servers. Absolute `file://`
registries are read-only API fixtures, not publication destinations.

## Authentication

```sh
encore login
encore whoami
encore publish
encore logout
```

Login prints a browser URL and device code. Approve the request on the site.
The resulting credential is stored in the OS keyring, keyed by the complete
canonical index URL: libsecret on Linux, Keychain on macOS, Credential Manager
on Windows. There is no plaintext-file fallback. Logout revokes the credential
remotely before removing it locally.

Authentication commands accept `--registry <index-url>` outside a project.
For CI, inject a short-lived package-scoped `ENCORE_REGISTRY_TOKEN` and set
`ENCORE_REGISTRY_TOKEN_INDEX` to the intended registry. Both are required;
credentials must never be forwarded to another registry.

## Prepare a package

A package needs tracked `encore.toml` and source files:

```toml
[project]
name = "example_math"
version = "1.0.0"
encore = ">=0.0.0"
description = "Math helpers for Encore"
licence = "MIT"
dependencies = ["index@std"]

[publish]
exclude = ["notes/**"]
```

Run local verification before publication:

```sh
encore format --check
encore check
encore test
encore publish --dry-run
encore publish
```

The dry run selects tracked files, validates and creates the exact archive,
without authentication, network requests or remote changes. Git is required
locally for tracked-file selection and portable deterministic archives, but a
commit, remote, GitHub account and clean worktree are not required.

Root `path@` dependencies are rewritten in the staged manifest to exact
`index@name@version` references. The original manifest is not changed. Publish
those dependencies first. Private `workspace@` refrains remain bundled under
`workspace/`. Git dependencies are still supported by the compiler; do not
confuse Git source installation with registry publication.

## API and immutable versions

The client discovers schema-1 capabilities at `<index>/config.json`. Public
package metadata is obtained from `/api/v1/packages/<name>` on the same origin.
Publication uploads chunks of 64 KiB and commits the SHA-256-verified archive.
Authenticated requests use the native HTTP client and never follow redirects.
A failed or incompatible service is an error, not a reason to use GitHub.

The current publisher accepts archives up to 4 MiB. A repeated publication of
the same version and identical archive is idempotent. Different bytes for an
existing version are rejected. Increment `[project].version` for changes.
`--release-name` selects the nametag; `--release-only` is no longer supported.
Archives may contain only regular files and directories, with `encore.toml`
at their root. Links, special files and path traversal are rejected.

New consumers select the highest compatible, non-yanked SemVer version.
Existing consumers stay on their lockfile until `encore update`. Yanking does
not delete archives or invalidate existing locked builds. Changing registry
requires an explicit update; caches are isolated by canonical registry URL.

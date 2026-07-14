# Encore

Encore is a self-hosted programming language and native compiler built around
EHIR (Encore High Intermediate Representation) and LLVM.

The current development line is `0.1.3`. Python compiler development ended at
`0.1.2`; current sources are compiled only by the native Encore compiler.

## Install

Linux and macOS:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-language/encore/trunk/install.sh | sh
export PATH="$HOME/.encore/bin:$PATH"
```

The installer verifies the release checksum. Set `ENCORE_VERSION` to install a
specific tag, or update explicitly with:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-language/encore/trunk/install.sh | \
  sh -s -- --update

curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-language/encore/trunk/install.sh | \
  sh -s -- --version 1.0.0
```

Use `--install-dir <path>` for a custom location and `--uninstall` to remove
the installation.
Set `ENCORE_RELEASE_BASE_URL` to an HTTPS release mirror containing archives
and their `.sha256` files. `file://` URLs are accepted for offline installation
and installer testing.

Building programs requires `clang` or a configured target toolchain. Resolving
packages from the official index also requires `curl`, `tar`, and either
`sha256sum` or `shasum`.

## Commands

```sh
encore init --name hello
encore build --profile release
encore run -- arg1 arg2
encore test
encore add <package>
encore sync
encore install --path .
encore target
encore target list
encore help build
```

`encore add json` resolves `index@json` through the official sparse package
index at `encore-language/index`. Published source archives are downloaded from
GitHub Releases, verified with SHA-256, and cached locally. Existing lockfiles
continue to use their exact archive and checksum without refreshing the index.

Cross-compile using an LLVM-compatible target triple:

```sh
encore build --target aarch64-unknown-linux-gnu --sysroot /opt/aarch64
```

Toolchains can also be configured in `encore.toml`. See
[`Targets And Cross-Compilation`](docs/enbook-en/src/targets.md).

## Repository Layout

| Path | Purpose |
| --- | --- |
| `index/core` | low-level language library and portable C runtime |
| repository root | native compiler frontend and CLI |
| `index/ehir` | native EHIR representation and parser |
| `index/ehir-llvm-backend` | native LLVM backend |
| `index/std` | application standard library |
| `index/rich` | terminal rendering and compiler/test progress |
| `examples` | executable language examples |
| `docs/enbook-en` | language and toolchain documentation |

## Native Development

With an existing native compiler at `target/extreme/encore`, run from the repository root:

```sh
./target/extreme/encore build --profile extreme
./target/extreme/encore test
```

Regular CI builds the native compiler and runs package tests on Linux and
macOS. Tagged commits run the full self-host and release verification workflow,
then publish Linux and macOS archives with checksums.

Prepare a stable release version from a clean worktree with
`scripts/set-version.sh MAJOR.MINOR.PATCH`. `VERSION` is canonical; CI verifies
that the native CLI, compiler manifest, README, and PKGBUILD template stay
synchronized. Tagged releases include a generated Arch Linux `PKGBUILD` pinned
to the SHA-256 of both Linux architecture archives. The complete maintainer
procedure is in [`RELEASING.md`](RELEASING.md).

## License

MIT. See [LICENSE](LICENSE).

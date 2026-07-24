# Encore

Encore is a self-hosted programming language and native compiler built around
EHIR (Encore High Intermediate Representation) and LLVM.

The current development line is `0.1.4`. Python compiler development ended at
`0.1.2`; current sources are compiled only by the native Encore compiler.

## Install

Linux and macOS:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh | sh
export PATH="$HOME/.encore/bin:$PATH"
```

The installer verifies the release checksum. Set `ENCORE_VERSION` to install a
specific tag, or update explicitly with:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh | \
  sh -s -- --update

curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh | \
  sh -s -- --version 0.1.4
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
encore check
encore lint
encore format --check
encore add <package>
encore sync
encore install --path .
encore self update
encore self channel beta
encore target
encore target list
encore help build
```

`encore self update` updates the complete managed compiler distribution while
keeping `encore update` dedicated to project dependencies. Encore release
channels are `stable`, `beta`, and `nightly`:

```sh
encore self channel              # show the selected channel
encore self channel nightly      # persist a channel
encore self update --check
encore self update
encore self install 0.2.0        # install an exact immutable release
```

Updates use the native HTTPS stack, verify the release SHA-256, validate the
archive, and replace the installation transactionally. A failed update leaves
the previous compiler usable. Set `ENCORE_SELF_UPDATE_BASE_URL` to an HTTPS
release mirror; `file://` is accepted for offline testing.

Build profiles have distinct optimization contracts:

- `debug`: `-O0`, debug information, and frame pointers.
- `release`: portable `-O2` code with assertions disabled.
- `extreme`: `-O3`, ThinLTO through LLVM `lld`, 32-byte hot-loop alignment,
  and the native host CPU when building for the host without an explicit
  `target-cpu`.

Use `release` for distributable binaries that must run on a broad CPU baseline.
Use `extreme` for the fastest local or explicitly targeted production binary.

`encore add json` resolves `index@json` through the official sparse package
index at `encore-ecosystem/encore-index`. Published source archives are downloaded from
GitHub Releases, verified with SHA-256, and cached locally. Existing lockfiles
continue to use their exact archive and checksum without refreshing the index.
The complete user and author workflows are documented in
[`Packages And Build Scripts`](docs/enbook-en/src/packages.md) and
[`Publishing Packages`](docs/enbook-en/src/publishing-packages.md).

The official package set includes `std`, `json`, `rich`, `toml`, `log`,
`colorterm`, `dict`, `color`, and `geometry`. Index metadata and
contribution rules live in
[`encore-ecosystem/encore-index`](https://github.com/encore-ecosystem/encore-index).

Cross-compile using an LLVM-compatible target triple:

```sh
encore build --target aarch64-unknown-linux-gnu --sysroot /opt/aarch64
```

Toolchains can also be configured in `encore.toml`. See
[`Targets And Cross-Compilation`](docs/enbook-en/src/targets.md).

## Repository Layout

| Path | Purpose |
| --- | --- |
| repository root | native compiler frontend and CLI |
| `src` | compiler, package manager, diagnostics and CLI implementation |
| `tests` | end-to-end compiler tests |
| `examples` | executable language examples |
| `docs/enbook-en` | language and toolchain documentation |

Compiler and standard-library packages are published through
`encore-ecosystem/encore-index`; they are not duplicated in this repository.

## Native Development

With an existing native compiler at `target/extreme/encore`, run from the repository root:

```sh
./target/extreme/encore build --profile extreme
./target/extreme/encore test
```

Regular CI downloads the latest complete trusted release, builds the compiler
twice, requires byte-identical stage-1 and stage-2 binaries, and runs tests on
all five supported native targets. Version tags publish self-contained
toolchain archives, checksums, and update-channel manifests:

- `vMAJOR.MINOR.PATCH` publishes stable;
- `vMAJOR.MINOR.PATCH-beta.N` publishes beta;
- `vMAJOR.MINOR.PATCH-nightly.YYYYMMDD` publishes nightly.

`VERSION`, `encore.toml`, and `src/version.enq` must contain the tag version.

## License

MIT. See [LICENSE](LICENSE).

# Encore

Encore is a self-hosted native programming language built on EHIR and LLVM

This local working tree includes standard HTTP runtime integration. Linux
builds require OpenSSL and c-ares >=1.34 development headers and libraries;
cross-build sysroots need those libraries too. This change is not an official
compiler release.

## Install

Linux and macOS require `curl`, `tar`, `clang`, and either `sha256sum` or
`shasum`:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh | sh
export PATH="$HOME/.encore/bin:$PATH"
```

The installer downloads the release for the current architecture, verifies its
SHA-256 checksum and replaces an existing installation transactionally.

```sh
# Install an exact release.
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh |
  sh -s -- --version 0.0.0-neumann

~/.encore/bin/encore --version

# Remove Encore.
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/encore-ecosystem/encore/trunk/install.sh |
  sh -s -- --uninstall
```

Use `--install-dir <path>` for another location. The installer supports Linux
on x86-64 and AArch64, and macOS on Apple Silicon (M1 or newer).

## Quick Start

```sh
encore init --name hello
cd hello
encore run
encore test
encore build --profile release
```

Useful commands:

```sh
encore check
encore format
encore lint
encore add <package>
encore build --target <llvm-triple>
encore self update
```

Language, package and cross-compilation documentation is in
[`docs/enbook-en`](docs/enbook-en/).

## Development

This checkout contains the compiler and language server (`lsp/`). Its 17 system
libraries and backend packages are pinned Git submodules from
[`encore-language-index`](https://github.com/encore-language-index).
Clone their exact versions with the compiler:

```sh
git clone --recurse-submodules --branch trunk https://github.com/encore-ecosystem/encore.git
cd encore
# Also run this after pulling a commit that changes package pins.
git submodule update --init --recursive
```

An installed Encore compiler can bootstrap this complete checkout:

```sh
encore build --profile extreme
./target/extreme/encore test
(cd lsp && ../target/extreme/encore build --profile release)
```

The final two bootstrap compilers must be byte-identical. See
[SDK development](docs/sdk-submodules.md) for package changes, source snapshots
and release provenance. Release distributions contain ordinary SDK files and
work without Git or an index connection.

For the published `v0.1.5-neumann` seed, first fetch that Git tag and run
`bash scripts/ci-seed-build.sh /path/to/0.1.5/bin/encore v0.1.5-neumann build --profile extreme`.
The script builds a temporary compiler from the tagged sources with `Div`
support, then builds the current compiler against the seed's library versions.
Current compiler sources retain `Path / component` syntax. Subsequent stages
use the current checkout's libraries and independent compiled-package caches.

## License

[MIT](LICENSE)

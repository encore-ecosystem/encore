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

This checkout contains the compiler, system libraries and backends (`packages/`),
and language server (`lsp/`). No separate package-index checkout is required.
An installed Encore compiler can bootstrap it:

```sh
encore build --profile extreme
./target/extreme/encore test
(cd lsp && ../target/extreme/encore build --profile release)
```

The final two bootstrap compilers must be byte-identical.

## License

[MIT](LICENSE)

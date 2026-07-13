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

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/encore-language/encore/trunk/install.ps1 | iex
```

The installer verifies the release checksum. Set `ENCORE_VERSION` to install a
specific tag, or run the installer again to update. Uninstall with
`install.sh --uninstall` or `install.ps1 -Uninstall`.

Building programs requires `clang` or a configured target toolchain.

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
```

Cross-compile using an LLVM-compatible target triple:

```sh
encore build --target aarch64-unknown-linux-gnu --sysroot /opt/aarch64
```

Toolchains can also be configured in `encore.toml`. See
[`Targets And Cross-Compilation`](docs/enbook-en/src/targets.md).

## Repository Layout

| Path | Purpose |
| --- | --- |
| `core` | low-level language library and portable C runtime |
| `index/encore` | native compiler frontend and CLI |
| `index/ehir` | native EHIR representation and parser |
| `index/ehir-llvm-backend` | native LLVM backend |
| `index/std` | application standard library |
| `index/rich` | terminal rendering and compiler/test progress |
| `examples` | executable language examples |
| `docs/enbook-en` | language and toolchain documentation |

## Native Development

With an existing native compiler at `index/encore/target/extreme/encore`:

```sh
cd index/encore
./target/extreme/encore build --profile extreme
./target/extreme/encore test
```

CI performs two native self-host generations and tests Linux and macOS release
packages. Tagged commits publish portable archives and checksums, including
Windows artifacts from the release workflow.

## License

MIT. See [LICENSE](LICENSE).

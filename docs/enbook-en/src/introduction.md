# Introduction

Encore is a self-hosted programming language and native compiler built around
EHIR, the Encore High Intermediate Representation, and LLVM.

This book documents project setup, language syntax, packages, target
toolchains, the memory model, and the standard library.

## Repository Layout

| Path | Purpose |
| --- | --- |
| repository root | native compiler frontend and CLI |
| `src` | compiler, package manager, diagnostics and CLI |
| `tests` | compiler integration tests |
| `examples` | executable language examples |
| `docs/enbook-en` | this user guide |

Core, EHIR, backend, and standard-library packages are distributed through the
official `encore-ecosystem/encore-index` sparse registry.

## Requirements

- an installed Encore native compiler;
- `clang` or another configured target toolchain.
- `curl`, `tar`, and `sha256sum` or `shasum` when resolving index packages.

Verify the installation and target:

```sh
encore --version
encore target
```

Python is not part of the compiler or runtime. The retired Python compiler is
preserved only in the `v0.1.2` release history as a bootstrap fallback.

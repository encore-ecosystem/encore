# Introduction

Encore is an experimental programming language and compiler built around EHIR,
the Encore High Intermediate Representation. The `0.1.x` line targets an open
beta: the local compiler, EHIR/LLVM backend, `core`, `std`, examples and
regression tests are intended to be usable for real small programs.

This book documents the beta surface that users should rely on before reading
compiler sources:

- project setup and CLI workflow;
- core language syntax used by the regression suite and examples;
- package manifests and native build-script integration;
- the public `core` and `std` APIs.

Linux is the primary validated beta platform. Other platforms are part of the
design, but broad cross-platform validation is not complete yet.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `src/encore` | Python compiler frontend and CLI |
| `ehir` | EHIR library and compiler pipeline |
| `ehir-llvm-backend` | LLVM backend for EHIR |
| `core` | low-level Encore package injected by the compiler |
| `std` | application standard library package |
| `bootstrap` | language regression tests and bootstrap examples |
| `index` | practical example packages |
| `docs/enbook-en` | this user guide |

## Requirements

- Python `>=3.13,<3.14`
- `uv`
- `clang`
- LLVM-compatible native toolchain for the bundled backend

Install the project from the repository root:

```sh
uv sync
uv run encore --help
```

When running from a package subdirectory, pass the root project to `uv` if
needed:

```sh
uv run --project /path/to/encore encore test --no-cache
```

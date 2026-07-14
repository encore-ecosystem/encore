# Introduction

Encore is a self-hosted programming language and native compiler built around
EHIR, the Encore High Intermediate Representation, and LLVM.

This book documents project setup, language syntax, packages, target
toolchains, the memory model, and the standard library.

## Repository Layout

| Path | Purpose |
| --- | --- |
| repository root | native compiler frontend and CLI |
| `index/ehir` | native EHIR library and parser |
| `index/ehir-llvm-backend` | native LLVM backend |
| `index/core` | low-level package and C runtime |
| `index/std` | application standard library |
| `index/rich` | terminal rendering and progress UI |
| `examples` | executable language examples |
| `docs/enbook-en` | this user guide |

## Requirements

- an installed Encore native compiler;
- `clang` or another configured target toolchain.

Verify the installation and target:

```sh
encore --version
encore target
```

Python is not part of the compiler or runtime. The retired Python compiler is
preserved only in the `v0.1.2` release history as a bootstrap fallback.

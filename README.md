# Encore

Encore is an experimental programming language and compiler built around EHIR
(Encore High Intermediate Representation). The current release line is focused
on an open beta: real programs should be possible, but APIs and diagnostics may
still change quickly.

## Status

Current compiler version: `0.1.2`.

The beta target is a usable local toolchain with:

- project initialization, dependency sync, build, run and test commands;
- EHIR/LLVM code generation through the bundled backend;
- `core` and `std` libraries for common CLI and systems-style programs;
- native support code provided by `core/build.enq`;
- practical examples in `index/`.

## Requirements

- Python `>=3.13,<3.14`
- `uv`
- `clang`
- an LLVM-compatible toolchain for the current EHIR LLVM backend

Linux is the primary tested platform for this beta. Cross-platform support is
being designed around `core/build.enq`, conditional compilation and native link
configuration.

## Installation

```sh
git clone https://github.com/encore-language/encore
cd encore
uv sync
uv run encore --help
```

When running Encore from a subdirectory, use `--project` if `uv` cannot find the
root project automatically:

```sh
uv run --project /path/to/encore encore run
```

## Project Commands

```sh
encore init --name <name>
encore sync
encore build
encore run
encore test
encore add <package>
```

Useful beta flags:

```sh
encore build --no-cache
encore run --no-cache
encore test --no-cache
encore test --filter vec
encore build --cfg linux
```

## Examples

Applied examples live in `index/`.

```sh
cd index/echo
uv run --project ../.. encore run -- hello beta

cd ../wc
uv run --project ../.. encore run -- src/main.enq

cd ../hello_server
uv run --project ../.. encore run
```

The example set includes CLI tools, sorting algorithms, path/string demos,
networking smoke tests, a terminal donut renderer and small data-structure
programs.

## Documentation

User-facing beta docs now live in `docs/enbook-en/src/`:

- `getting-started.md` covers setup, manifests, commands and tests.
- `language-basics.md` covers imports, functions, structs, enums, traits,
  loops, `match`, `with` and common syntax.
- `standard-library.md` covers the public `std` surface.

Package-specific references are also available in `core/README.md` and
`std/README.md`.

## Validation

The current beta gate is tracked in `TODO.md`. The latest completed validation
covered:

```sh
cd bootstrap
uv run --project .. encore test --no-cache

cd ..
uv run ruff check src core ehir/src ehir-llvm-backend/src
uv run ty check src/encore/modes/build.py src/encore/modes/test.py
```

Known non-blocking beta limitations are documented in `TODO.md`.

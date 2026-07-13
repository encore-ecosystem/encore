# Getting Started

Create a package in an empty directory:

```sh
uv run --project /path/to/encore encore init --name hello
```

`encore init` creates:

```text
encore.toml
src/main.enq
README.md
.gitignore
```

A minimal executable is:

```enq
import std::io::println

fn main() -> u32 {
    println("hello")
    ret 0_u32
}
```

If the package uses `std`, add it to `encore.toml`:

```toml
[project]
name = "hello"
target = "auto"
version = "0.0.0"
description = ""
readme = "README.md"
licence = "MIT"
dependencies = [
    "path@/path/to/encore/std",
]
```

For packages inside this repository's `index/`, examples usually use
`path@../../std`.

## Commands

Run these from the package directory:

```sh
encore sync
encore build
encore run
encore test
encore add <package>
encore update
```

Common beta flags:

```sh
encore build --no-cache
encore run --no-cache -- arg1 arg2
encore test --no-cache
encore test --filter dict
encore build --cfg linux
encore build --profile release
```

`encore run` is only available for executable packages. Program arguments after
`--` are passed to the compiled binary.

## Tests

Unit tests are ordinary functions marked with `#attr(test)`. `encore test`
discovers them across loaded refrains, compiles each test with a small harness,
and treats the test as passed when it returns `true`.

```enq
#attr(test)
fn math_works() -> bool {
    ret 2_u32 + 2_u32 == 4_u32
}
```

Test functions should:

- return `bool`;
- take no parameters;
- be non-generic;
- use `true` for pass and `false` for fail.

The test harness wraps the function in a generated executable `main`, so the
rest of the program can stay unchanged.

## Examples

Practical packages live in `index/`:

```sh
cd index/echo
uv run --project ../.. encore run -- hello beta

cd ../wc
uv run --project ../.. encore run -- src/main.enq

cd ../dict
uv run --project ../.. encore run
```

The examples cover CLI programs, sorting, dictionaries, paths, strings,
filesystem operations, Unicode output, networking and terminal rendering.

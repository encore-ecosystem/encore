# Packages And Build Scripts

Encore packages are configured by `encore.toml`.

```toml
[project]
name = "my_package"
target = "auto"
version = "0.0.0"
description = ""
readme = "README.md"
licence = "MIT"
dependencies = [
    "path@../std",
]
```

## Project Fields

| Field | Meaning |
| --- | --- |
| `name` | package name |
| `target` | `auto`, `executable`, `static_lib` or `shared_lib` |
| `version` | package version string |
| `description` | package description |
| `readme` | readme path |
| `licence` | license string |
| `dependencies` | dependency references |
| `build` | optional build script path |

`core` is a system dependency injected by the compiler. Do not add `sys@core`
manually.

## Dependency References

Supported dependency references:

- `path@../some-package`
- `git@https://github.com/org/repo`
- bare index names through `encore add <name>`

`encore sync` resolves dependencies and writes `encore.lock`.
`encore update` pulls git dependencies and rewrites the lockfile.

## Package Layout

Executable package:

```text
encore.toml
src/main.enq
```

Library package:

```text
encore.toml
src/lib.enq
src/module/mod.enq
```

Unit tests live next to the code they exercise and are marked with
`#attr(test)`.

`src/lib.enq` commonly re-exports modules:

```enq
pub import refrain::fmt
pub import refrain::vec
```

## Conditional Compilation

Use `#cfg(...)` to compile declarations for selected environments:

```enq
#cfg(linux)
pub fn os_name() -> str {
    ret "linux"
}

#cfg(windows)
pub fn os_name() -> str {
    ret "windows"
}
```

Pass extra flags from the CLI:

```sh
encore build --cfg linux
encore test --cfg feature=my_feature
```

## Native Build Scripts

Build scripts let packages publish native link metadata. `index/core/build.enq` is the
reference pattern. It writes JSON to the path passed as argv `1`:

```json
{
  "native": {
    "libraries": [
      {"name": "encore_core_native", "path": "runtime.c"}
    ],
    "search_paths": [],
    "frameworks": [],
    "link_args": []
  }
}
```

Enable a build script in `encore.toml`:

```toml
[project]
name = "native_package"
target = "auto"
build = "build.enq"
dependencies = []
```

Native library entries can name a system library or a file path. Optional `cfg`
fields let metadata apply only to matching compile-time configurations.

## Validation Commands

Release-gate validation uses the native compiler:

```sh
compiler="$PWD/target/extreme/encore"
for package in index/core index/ehir index/ehir-llvm-backend index/rich index/std; do
    (cd "$package" && "$compiler" test)
done
./target/extreme/encore test
```

# Beta Notes

The `0.1.x` beta is intended for testing and feedback, not long-term API
stability.

## Validated Surface

The current release gate validates:

- local compiler commands: `init`, `sync`, `add`, `build`, `run`, `test`,
  `update`;
- EHIR and the bundled LLVM backend;
- `core` and `std` workflows for vectors, dictionaries, strings, paths,
  filesystem access, process/fmt, math/random, time and networking;
- language regression coverage for `for`, iterators, `match`, methods,
  ownership/drop behavior, generic inference and `dyn Trait`;
- negative tests with expected diagnostics.

## Known Limits

- Linux and macOS are the validated native release platforms.
- Other LLVM-compatible targets are supported through explicit toolchain and
  runtime configuration but do not receive production compiler archives.
- Package index behavior is usable for beta testing and may change before a
  stable release.
- `async`/`await`, MLIR integration, structural inheritance and long-term
  backend dialect design are outside this release gate.
- Full-repository static type checking still has known baseline diagnostics
  outside the release-critical build/test command paths.

## Reporting Issues

When reducing a compiler or library issue, include:

- the package's `encore.toml`;
- the smallest `.enq` file that reproduces it;
- the exact command, for example `encore test --filter dict`;
- the complete diagnostic output.

Prefer adding a regression test as a `#attr(test)` function in the relevant
module when the behavior is meant to be part of the beta surface.

# Release Notes

## Encore 0.2.0

- Compile-time decorators support arguments, stacking, functions, methods,
  synchronous code, and asynchronous code. Decorator calls lower directly to
  hidden implementations without runtime callable dispatch.
- Immutable `static` declarations enable named decorator-manager syntax such
  as `@RENDER_PROFILE.profile("draw_frame")`.
- The `profile` package provides process-wide aggregated nanosecond timing.
- The LLVM backend emits shared generic, ownership, trait-dispatch, and graph
  support once per compilation bundle instead of duplicating it in every code
  generation unit.
- Large generated state machines avoid the quadratic source mem2reg path while
  retaining entry-block stack-allocation hoisting.
- Clean self-host compilation is substantially faster and uses much less peak
  memory than 0.1.5.

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
- The v1 package index selects the last non-yanked release and does not yet
  support manifest version constraints or package search.
- MLIR integration, structural inheritance and long-term backend dialect
  design are outside this release gate.
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

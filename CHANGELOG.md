# Changelog

## 0.2.0 — 2026-08-11

### Added

- Compile-time `#attr(decorator)` definitions and `@decorator(...)`
  applications for free functions and methods.
- Parameterized and stacked decorators with deterministic Python-style
  composition order.
- Receiver-qualified decorators, including
  `@RENDER_PROFILE.profile("draw_frame")`.
- Sync and async profiling decorators through the new `profile` package.
- Monotonic nanosecond `perf_counter_ns` platform API.
- A version-matched `encore-lsp` binary in every native compiler distribution.

### Changed

- Generic specialization, trait dispatch, ownership helpers, and ERN graph
  edge helpers are emitted once in a support code-generation unit.
- Large EHIR state machines use a bounded linear normalization fallback and
  leave scalar promotion to LLVM.
- Compiler, EHIR, LLVM, and test cache identities now follow the compiler
  version and invalidate the pre-0.2 layouts.
- Native CI pins one immutable `encore-index` revision per run and validates
  formatter, checker, linter, LSP protocol, and self-hosting convergence before
  producing release candidates.

### Performance

- A clean release self-host on the development machine fell from 313.6 seconds
  to 86.9 seconds, with backend peak resident memory reduced from roughly
  7.5 GiB to roughly 1.73 GiB.

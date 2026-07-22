# Encore repository guide

This file defines repository-wide guidance for coding agents. More specific
`AGENTS.md` files may refine these rules for their subtrees.

## Product direction

Encore is a self-hosted native programming language built around EHIR and
LLVM. The repository is growing into a coherent language and application
platform consisting of:

- the compiler, package manager, formatter, diagnostics, linting and type
  analysis;
- a lightweight native, AI-first IDE inspired by Zed rather than VS Code;
- Graphene, a real-time engine and editor with agent integration;
- synchronous and asynchronous networking, HTTP, and a typed web framework.

Prefer shared foundations over parallel implementations. The compiler, CLI
tools, LSP, IDE and Graphene should consume a common incremental semantic
analysis API. Likewise, blocking and asynchronous networking should share
protocol parsers, buffers and state machines rather than becoming two stacks.

## Repository map

- `src/`: native compiler frontend, project/build logic and CLI.
- `index/core`: low-level language library and portable C runtime.
- `index/ehir`: EHIR representation and parser.
- `index/ehir-llvm-backend`: LLVM backend.
- `index/lsp`: native Encore language server.
- `index/encore-ui`: retained native UI toolkit.
- `index/graphene`: Graphene engine, editor, RHI and examples.
- `index/std`: standard application library.
- `benchmark`: equivalent Encore and Rust benchmarks.
- `examples`: small executable language examples.
- `docs/enbook-en`: language and toolchain documentation.

## Architecture principles

- Keep EHIR and public APIs backend-neutral. Do not leak LLVM, Vulkan or OS
  handles into language- or engine-level APIs.
- Preserve Encore's graph memory model and ERN-node concept when optimizing
  memory management.
- Optimize cold compilation as a first-class workload. Measure before and
  after material compiler changes without relying on a warm cache.
- Design module boundaries so independently compiled EHIR modules can later be
  cached and scheduled in parallel without materializing rewritten temporary
  projects.
- Keep editor interaction off rendering and other latency-sensitive paths.
  Avoid rebuilding whole widget trees for hover, focus or other local visual
  state changes.
- Keep the IDE and Graphene usable as independent processes. Their deep
  integration belongs in a versioned IDE plugin/protocol, not hard-coded UI
  coupling.
- The IDE should be fast, native and keyboard-friendly, taking inspiration
  from Zed's architecture and interaction model. Plugin support is a core
  requirement, not a later workaround.
- Build the IDE in Encore on top of `encore-ui`. Develop `encore-ui` into a
  convenient, functional and high-performance native toolkit suitable for a
  production code editor; editor requirements should drive reusable toolkit
  improvements rather than application-only workarounds.
- Zed is a product and architecture reference, not a compatibility target.
  Do not constrain the plugin API around Zed extension compatibility unless a
  concrete future requirement justifies it.
- New standalone libraries do not need the `encore` prefix. Choose concise
  names based on their role and avoid copying Rust branding into public APIs.

## Language tooling

Extend the existing LSP toward a reusable incremental analysis database rather
than implementing separate parsers and semantic models for each tool. The same
source of truth should power:

- compiler diagnostics and type checking;
- command-line check, lint and format tools;
- LSP completion, navigation, hover, rename and diagnostics;
- IDE features and structured tools exposed to AI agents;
- Graphene script and scene-aware development workflows.

Docstrings are language syntax and structured compiler data, not merely text
scraped by the IDE. Preserve them through AST and module metadata so imported
symbols can expose documentation without reparsing their source.

## Development workflow

The compiler is self-hosted. With an existing native compiler, common commands
from the repository root are:

```sh
./target/extreme/encore build --profile extreme
./target/extreme/encore test
python3 benchmark/run.py
```

Package-specific commands should be run from that package directory. Read its
README and `encore.toml` first. For example, the LSP integration suites are
documented in `index/lsp/README.md`.

Before modifying code:

1. Inspect the closest README, manifest, tests and relevant public interfaces.
2. Check `git status` and preserve unrelated or user-generated changes.
3. Add focused tests for behavior changes when practical.

Before handing work back:

1. Run the narrowest relevant tests, then broader suites in proportion to risk.
2. Run `git diff --check`.
3. Report what was verified and what was not.
4. Do not commit, merge, push or discard user changes unless requested.

For performance work, record the command, profile, workload and before/after
numbers. Correctness checksums must match before comparing benchmark timings.

## Change quality

- Prefer small, composable public APIs and explicit ownership/lifetime rules.
- Keep compatibility unless the task explicitly authorizes a breaking change.
- Update user-facing documentation with syntax, CLI or public API changes.
- Avoid placeholder abstractions that merely rename an existing layer.
- Treat crashes, event-loop stalls, unbounded waits and resource leaks as
  correctness bugs, not only performance issues.

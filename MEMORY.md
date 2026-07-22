# Working memory

This is my long-term context for continuing work with the repository owner. It
is intentionally informal and may be updated whenever a decision, preference
or result would otherwise be easy to lose between sessions. Canonical agent
rules belong in `AGENTS.md`; product documentation belongs in the relevant
README or `docs/` page.

## Owner preferences

- Communicate in Russian unless there is a reason to use English.
- Prefer Python with `uv` for repository scripting and test tooling when a
  native Encore implementation is not appropriate. Do not introduce Ruby
  runtime dependencies.
- Prefer implementation and measurement over speculative design-only work.
- Performance matters strongly: cold compiler time, runtime throughput and UI
  responsiveness should be measured on realistic projects.
- Significant improvements to the compiler may adjust global memory behavior,
  but must retain the graph model and ERN nodes.
- Do not introduce view/slice APIs yet; their safety model has not been chosen.
- Preserve local, generated and experimental files unless explicitly asked to
  remove or commit them.
- When valid, desirable Encore syntax exposes a compiler limitation, fix the
  compiler and add semantic coverage instead of leaving an awkward workaround
  merely to make the immediate code compile. Workarounds are acceptable only
  as explicitly temporary diagnostics, not as the finished solution.

## Accepted long-term direction

- Build one shared incremental language-analysis foundation and use it for the
  compiler, check/lint tools, LSP, IDE, documentation and AI semantic tools.
- Add first-class structured docstrings.
- Build a lightweight, functional, native AI IDE inspired by Zed, not a VS
  Code clone. Implement it in Encore on top of `encore-ui`; evolve the toolkit
  to a highly convenient, functional and performant production UI foundation.
  The IDE must support plugins.
- Zed extension compatibility is not required. Borrow good architectural and
  interaction ideas without inheriting its extension contracts.
- Graphene will use this IDE as its default code editor and gain active AI-agent
  integration. Implement the tight Graphene/IDE bridge as a plugin with a
  versioned boundary so both applications remain independently usable.
- Build both synchronous and asynchronous networking for Encore on shared low-
  level implementations, followed by HTTP and a typed web framework analogous
  in purpose to Axum.
- New libraries and frameworks may use independent names; they do not need an
  `encore-` prefix.

## Current technical context

- The native compiler is self-hosted and uses EHIR plus LLVM.
- `index/lsp` already implements a substantial native language server. Evolve
  it toward shared incremental analysis instead of starting a competing LSP.
- The `extreme` profile is intended to be the maximum-performance local build:
  O3, ThinLTO/lld, hot-loop alignment and native CPU targeting where valid.
- The benchmark suite compares equivalent Encore and Rust programs and checks
  deterministic output before accepting timings.
- Graphene is an Encore real-time engine/editor using a backend-neutral RHI,
  currently backed by Vulkan. `encore-ui` is its retained native UI layer.

## Recent repository state

- `feature/graphene-vulkan-rhi` was merged locally into `trunk` in merge commit
  `ed1b0ee` after the Graphene/editor responsiveness work was committed as
  `88ca7c5`.
- At that point local `trunk` was ahead of `origin/trunk`; nothing was pushed.
- The primitives example had intentional uncommitted scene/material changes.
  Always inspect current status instead of assuming those files are disposable.

## Likely implementation order

1. Structured docstrings and the reusable incremental analysis database. This
   is the explicitly selected next major direction.
2. Check/type diagnostics, linting, formatting and LSP migration onto it.
3. Minimal native AI IDE with a stable plugin host.
4. Graphene integration plugin and agent-facing scene tools.
5. Async runtime plus TCP/UDP/DNS and a blocking facade.
6. TLS/HTTP, then the typed web framework.

This ordering is a working preference, not an immutable specification. Update
it when measurements or implementation constraints suggest a better path.

## Open decisions worth revisiting

- IDE name and standalone library/framework names.
- Plugin architecture should start as a hybrid: sandboxed WASM for ordinary
  extensions and separate processes for LSP servers and heavyweight AI or
  Graphene tools. The exact ABI, capability model and lifecycle remain open.
- Exact docstring syntax and rendered markup conventions.
- Async task model, cancellation semantics and resource ownership.
- Whether analysis data is persisted on disk or initially remains in-memory.

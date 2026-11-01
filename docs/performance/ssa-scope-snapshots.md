# SSA scope snapshots during typed lowering

The baseline is `28dd220`, the converged 0.1.13 development compiler after
sharing foreign LLVM declarations. This iteration targets AST-to-EHIR
translation, the largest individual reported Graphene phase in that baseline.

Type inference for `if` and `match` creates temporary `LoweringScope` probes.
Previously each fork iterated over every known SSA value, rebuilt a parameter
vector and reconstructed its name table. Repeated probes in large functions
also repeatedly retained and dropped the same types. Stack sampling of a
four-module Graphene workload found `LoweringScope::fork` and incoming-owner
removal during `Type` cleanup on the active call stacks. Local variable lookup,
ownership classification and instruction-buffer operations were separately
timed; their combined cost did not explain most of the lowering time.

A probe now starts with empty local bindings and a retained parent reference
plus its captured binding count. Each local binding records the previous
position for its spelling. Lookup walks ancestors and follows rebinding history
back to the captured prefix. Parent appends and rebindings after a fork remain
invisible to that snapshot, while definitions added by the probe remain local.
Fork creation no longer copies a number of values proportional to the parent
scope size. Lookup cost depends on snapshot depth and subsequent rebindings;
each local binding adds one history index. Ancestor storage remains alive until
its last probe is released.

Explicit operand annotations, unit values, uppercase SSA names used in
comparisons, and the former fork's inherited operand classification are
preserved. Type and callable caches remain local to each scope. Scope storage
retains its existing exclusive marker and cannot be implicitly frozen or
sent across threads. There are no runtime C or cache-format changes.

One matched pair of complete native Graphene builds uses the preceding and
new converged `extreme` compilers, the same frozen workspace and dependency
sources, Linux x86_64, Clang/LLD 23.1.3, the `dev` profile and eight jobs. Each
cold build starts with an empty target and private compiled-artifact cache.
Dependency sources are preseeded and OS page cache is retained. Both runs use
the built-in phase timers; no tests, compiler builds or external profiler
overlap either timed build.

| Complete native build | Before | After |
|---|---:|---:|
| Cold build | 368.794 s | 338.092 s |
| Graphene AST-to-EHIR translation | 82.192 s | 63.240 s |
| Graphene semantic checking | 67.484 s | 64.614 s |
| Graphene LLVM IR emission | 53.776 s | 47.492 s |
| Unchanged build | 6.358 s | 6.404 s |

The cold build saves 30.70 seconds, an 8.33% elapsed-time reduction (1.09x
speedup). The reported AST-to-EHIR translation phase takes 23.06% less time.
All 17 owning EHIR payloads, all 17 native language archives and the native
executable match byte for byte. Camera, ordinary-function and CLI probes pass
after both cold and unchanged builds. Unchanged builds remain around
6.4 seconds. Other phases also vary between runs; this single matched pair
is not a statistical performance or CI guarantee and does not isolate every
part of the total improvement. The focused comparison below supports the
attribution to scope forks. Package phase times overlap and must not be added.

After this change the largest individual Graphene phases are semantic checking
at 64.61 seconds, AST-to-EHIR translation at 63.24 seconds and LLVM emission at
47.49 seconds. Import namespace expansion also appeared in the lowering stack
samples; its implementation is unchanged in this iteration.

The focused comparison uses identical workspace sources and four branch-heavy
Graphene modules: `main.enq`, `native_asset.enq`, `animation/asset.enq` and
`preview.enq`. Both diagnostic executables include matching operation timers
and use Clang 23 `-O3`. Their lowering timer excludes workspace loading,
serialization and hashing. The stack-sampling run is separate.

| Four-module diagnostic | Before | After |
|---|---:|---:|
| AST-to-EHIR translation | 53.380 s | 36.630 s |
| Whole process | 59.862 s | 43.126 s |
| Workspace loading | 5.665 s | 5.677 s |

The measured translation time falls by 31.38%, a 1.46x stage speedup. All four
serialized EHIR hashes and all measured operation counts match. This is one
matched diagnostic pair, not a statistical performance guarantee.

The reusable benchmark entry point is
[ast_lowering/main.enq](../../tests/fixtures/ast_lowering/main.enq).
Set `ENCORE_AST_BENCH_PROJECT` to a Graphene workspace with resolved, available
dependencies. It loads the binary workspace, lowers the four selected modules
and prints JSON with workspace and translation times and serialized EHIR
hashes. Without the environment variable it exits without running a benchmark.
This fixture has no additional operation timers or runtime instrumentation.

Validation includes 27 focused checks with the new self-hosted compiler:
SSA snapshot isolation and operand classification, released-parent lifetime,
node cleanup, direct typed EHIR construction, callable names, function cache
reuse, branch ownership, mutable bindings, node field translation, generic
places and calls, nominal types, thread contracts, match numeric context and
scopes, diverging branches, unit joins, moved and shadowed values, closures,
and compilation of the benchmark entry point. The internal regression creates
1,024 parent bindings and checks that its probe has zero local bindings before
adding one of its own. A negative regression rejects implicit freezing of the
mutable scope for a spawned function. The original 14-check subset also passes
when compiled with the preceding compiler.

Changed Encore sources pass formatting checks. Two fresh empty-cache `extreme`
self-host builds in Ubuntu 24.04 / Clang 18 Docker produce identical binaries:
`85fa8e18a05829be55c6c81ded59ab6274f46fac35067d6b6f6aee1cda9c1ea8`.
Their seed is the preceding converged development compiler at `28dd220`, not a
published 0.1.13 release. Native tests run on Linux x86_64 with Clang 23.1.3;
the new cross-platform CI matrix has not run.

Inputs, raw diagnostic counters, complete native build timings, artifact
comparisons and verification are recorded in
[ssa-scope-snapshots-2026-10-31.json](ssa-scope-snapshots-2026-10-31.json).

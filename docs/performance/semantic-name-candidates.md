# Exact-name candidates during semantic body checking

The baseline is `b41aed3`, the converged 0.1.13 development compiler after
SSA scope snapshots. Its recorded Graphene semantic check takes 64.61 seconds:
22.39 seconds of preparation, 28.86 seconds of parallel body work and
13.27 seconds of replay publication. The preceding complete cold build takes
338.09 seconds.

A separate diagnostic loads a binary Graphene workspace and runs cold semantic
preparation, eight-worker body checking and replay publication. The loader
exposes 256 root modules and 4,201 bodies; the complete native build's metadata
workspace has 258 modules and 4,211 bodies. These are distinct workloads and
their phase timings must not be treated as interchangeable.

The diagnostic reproduces the same split: 22.57 seconds of preparation,
29.40 seconds of body checking and 12.47 seconds of publication. Separate GDB
sampling collects 40 stops and 138 thread stacks. The runtime node graph lock
is the top frame in 78 stacks; 74 stacks include dropping a `SemanticMethod`.
These sample counts describe observed stacks, not percentages of elapsed time.
Exact-name method searches previously iterated over every method in the view,
creating and releasing temporary method records containing shared vectors even
when their names did not match. Parallel workers contended on node ownership
bookkeeping for these unrelated records.

`SemanticNameIndex` groups original record ordinals by exact spelling. Its
collision-checked key map selects a contiguous range of ordinal positions.
Queries allocate no result collection. Every overload retains its original
order. The checker builds callable and method indices lazily with the existing
module type index, sharing them across that module's checked functions.
Functions with additional generic-bound methods construct their method index
from the complete extended view. Ordinary module indices are immutable and
are released with the module check; they are not persisted or process-global.

Ordinary calls, associated calls, static value lookup, receiver calls,
syntax-driven method access and iterator protocol lookup now inspect exact-name
candidates. Receiver compatibility, generic specialization, visibility,
dependency recording and diagnostic rules are unchanged. Missing-member
suggestions still use the complete view. Indirect and overlaid views retain
local ordinals; invalid selections stop at the same first missing entry as the
original iterator. No runtime C or serialized cache format changes are needed.

The complete native comparison uses the preceding SSA-scope iteration's
baseline, captured earlier in the same session, and a newly measured candidate.
Both use the exact same frozen Graphene workspace path and source digests,
dependency sources, Clang/LLD 23.1.3, `dev` profile and eight jobs. Each cold build
starts with an empty target and a private compiled-artifact cache. Dependency
sources are preseeded; OS page cache is retained. The compilers are converged
`extreme` self-host builds. No tests, compiler builds or external profiler
overlap either timed native build.

| Complete native build | Before | After |
|---|---:|---:|
| Cold build | 338.092 s | 315.265 s |
| Graphene semantic check | 64.614 s | 43.556 s |
| Semantic preparation | 22.385 s | 22.469 s |
| Parallel body checking | 28.857 s | 7.249 s |
| Replay publication | 13.268 s | 13.731 s |
| Graphene AST-to-EHIR translation | 63.240 s | 63.524 s |
| Graphene LLVM IR emission | 47.492 s | 47.653 s |
| Unchanged build | 6.404 s | 6.370 s |

The cold build saves 22.83 seconds, a 6.75% elapsed-time reduction. The complete
semantic phase takes 32.59% less time; its body checking takes 74.88% less time,
a 3.98x speedup. All 17 owning EHIR payloads, all 17 native language archives
and the native executable match byte for byte. Camera, ordinary-function and
CLI probes pass after both cold and unchanged builds. Unchanged builds remain
around 6.4 seconds. This comparison describes one earlier baseline and one new
candidate run, not a statistical performance or CI guarantee. Package phase
times overlap and must not be added together.

The largest remaining individual Graphene phases are AST-to-EHIR translation
at 63.52 seconds, LLVM emission at 47.65 seconds and semantic checking at
43.56 seconds. Within semantics, environment preparation and replay publication
now dominate the parallel body work.

Both diagnostic executables use the same production source bodies, frozen
workspace, dependency sources and Clang 23 `-O3`. No concurrent builds, tests or
external profiler overlap these measured runs; GDB is a separate run.

| Cold semantic diagnostic | Before | After |
|---|---:|---:|
| Preparation | 22.571 s | 22.380 s |
| Parallel body checking | 29.396 s | 6.932 s |
| Replay publication | 12.465 s | 11.794 s |
| Whole process, including workspace load | 70.333 s | 47.044 s |
| Summed process CPU time | 204.809 s | 77.110 s |

Body checking takes 76.42% less elapsed time, a 4.24x speedup in this pair.
The package snapshot and every one of the 256 encoded module replay hashes
match byte for byte. The same 4,201 bodies are checked successfully in both
runs. Preparation and replay publication retain their existing implementations.
These observations describe one diagnostic pair, not a statistical or CI
performance guarantee.

The reusable entry point is
[semantic_checking/main.enq](../../tests/fixtures/semantic_checking/main.enq).
Set `ENCORE_SEMANTIC_BENCH_PROJECT` to a Graphene binary workspace with available
dependencies. It reports workspace loading, preparation, parallel checking and
publication durations, detailed environment counters, per-module worker
durations, and snapshot/replay hashes. Without this environment variable the
fixture exits without running the workload. Publication encodes and hashes
records without writing them to the compiler's artifact cache.

Validation includes 19 focused regressions covering candidate ranges, frozen
parallel readers, replay, package indices, nominal types, generic bounds,
receiver generics, associated calls, imported callables, trait members,
control flow, failed lookups, namespaces, qualified-body cache invalidation,
member queries, indirect/shared views, slices and spawned handles. All 14
selected internal semantic contracts also pass. Six checks pass when compiled
by the new compiler, including the formatted benchmark fixture and the updated
candidate-range regression with empty names, Unicode, case distinctions,
repeated names and two colliding keys read by four threads. The range contents
are compared with an independent linear scan of the input names.

Changed Encore sources pass formatting checks. Two fresh empty-cache `extreme`
self-host builds in Ubuntu 24.04 / Clang 18 Docker produce identical binaries:
`22c86f96c46fa6332efb52fb65e7d73c20a4e3367377dbade9cf1c8c8f5b66d7`.
Their seed is the preceding converged development compiler at `b41aed3`, not a
published 0.1.13 release. Native checks run on Linux x86_64 with Clang 23.1.3;
the new cross-platform CI matrix has not run.

Inputs, raw profiles, complete native build timings, artifact comparisons and
verification are recorded in
[semantic-name-candidates-2026-10-31.json](semantic-name-candidates-2026-10-31.json).

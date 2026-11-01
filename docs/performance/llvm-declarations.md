# Shared LLVM declarations

The baseline is `dc53233`, the first 0.1.13 development commit after nominal
type-resolution optimization. A fresh Graphene build with that converged
compiler takes 423.24 seconds. Graphene's largest individual reported phase is
LLVM IR emission at 104.41 seconds, followed by AST-to-EHIR lowering at
81.98 seconds and semantic checking at 68.33 seconds.

Package codegen previously lowered and rendered every foreign ordinary
function signature separately for every owned codegen unit. The focused
Graphene workload has 258 units, including small modules that still process
the complete declaration context. Diagnostic worker-duration sums are
457.64 seconds for function declarations and bodies, 168.84 seconds for type
declarations, and 33.51 seconds for building module views. These sums describe
overlapping parallel work and must not be added to wall-clock phase timings.

The backend now prepares immutable rendered foreign declarations once per
emission invocation, after installing the target context. Each codegen unit
reuses these strings and lowers its own definitions normally. Every original
declaration occurrence is retained in the shared plan; the per-unit symbol set
still determines which occurrence wins in declaration order. Selected-unit
ordering and duplicate selections are preserved.

One matched pair of full native Graphene builds uses the preceding and new
converged `extreme` compiler binaries, the same frozen workspace and dependency
sources, Linux x86_64, Clang/LLD 23.1.3, the `dev` profile and eight jobs. Each
cold build starts with an empty target and private compiled-artifact cache.
Dependency sources are preseeded and OS page cache is retained. Built-in phase
timers are enabled for both; no external profiler, tests or compiler builds
overlap the timed runs.

| Complete build measurement | Before | After |
|---|---:|---:|
| Cold native build | 423.235 s | 357.050 s |
| Unchanged native build | 6.414 s | 6.409 s |
| Graphene LLVM IR emission | 104.409 s | 47.557 s |
| Graphene AST-to-EHIR lowering | 81.983 s | 79.928 s |
| Graphene semantic checking | 68.332 s | 66.276 s |

The complete cold build saves 66.18 seconds, a 15.64% elapsed-time reduction
(1.19x speedup). The reported Graphene IR phase takes 54.45% less time.
Unchanged builds remain around 6.4 seconds. All 17 owning EHIR payloads, all
17 native language archives and the executable match byte for byte. Camera,
ordinary-function and CLI probes pass after cold and unchanged builds.
These results describe one matched pair, not a statistical performance or CI
guarantee. Package phase times overlap and must not be added together.

The largest remaining individual Graphene phase is AST-to-EHIR lowering at
79.93 seconds, followed by semantic checking at 66.28 seconds and LLVM emission
at 47.56 seconds.

The plan is neither process-global nor persistent. A later invocation rebuilds
it from the current declarations and target, including changes to signatures
and pointer width. Generic, ownership and runtime support retain their existing
emission paths. The ordinary emitter provides the uncached reference path.

The focused diagnostic loads normalized Graphene EHIR and its dependency
templates, prepares the package, then times eight-worker LLVM emission. Parsing,
preparation and output hashing are outside the emission timer. Both diagnostic
executables use the production lowering bodies, matching additional timers and
Clang 23 `-O3`. One pair was measured without concurrent builds or tests.

| Focused diagnostic | Before | After |
|---|---:|---:|
| LLVM emission | 91.722 s | 45.211 s |
| Whole process | 112.492 s | 66.109 s |
| Largest process RSS | 2,991.3 MiB | 2,991.0 MiB |

Emission takes 50.7% less elapsed time in this pair, a 2.03x speedup. All 258
LLVM module hashes and lengths match exactly. The resulting text still totals
2,039,678,637 bytes; sharing signature computation does not reduce IR volume.
These are diagnostic observations, not statistical or CI performance guarantees.

The new backend unit test compares complete emitted IR with the original
uncached path across 168 combinations: six release target triples plus 32-bit
Linux, one/two/eight workers, full/partial/reordered/duplicate/empty selections,
and changed signatures. A standalone regression also switches `usize`
declarations between 32-bit and 64-bit targets in one process with two workers.
All 15 backend regressions and 33 EHIR CLI/library/backend contracts pass locally
in Ubuntu 24.04 / Clang 18 Docker. Changed-source formatting and backend `check`
pass. The new native cross-platform CI matrix has not run.

Two fresh empty-cache `extreme` compiler builds are byte-identical:
`11627969485a6d0a1440a48e7b180b35ed692920251f869ca809bf83096362c0`.
Their seed is the preceding converged 0.1.13 development compiler, not a
published 0.1.13 release.

The reusable benchmark entry point is
[backend_emission/main.enq](../../tests/fixtures/backend_emission/main.enq).
Set `ENCORE_BACKEND_BENCH_INPUTS` to a directory with normalized `owned.ehir`
and `dependencies.txt`, containing one absolute dependency-template filename
per line in canonical dependency order. Optionally set
`ENCORE_BACKEND_BENCH_MODULE` to one owned module ID. Without an input directory
the fixture exits without running a benchmark. Its JSON reports load,
preparation and emission times, followed by module hashes and lengths.

Inputs, raw profiles, full-build timings, artifact comparisons and verification
are recorded in [llvm-declarations-2026-10-31.json](llvm-declarations-2026-10-31.json).

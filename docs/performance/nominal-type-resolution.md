# Nominal type resolution

This optimization starts the 0.1.13 development branch from `trunk` commit
`eb179fb1211e320734f04a6bbcf4c9cf36e7592c`, after the 0.1.12 release. The
port retains that release's callable parsing, unit operands, plugin diagnostics
and native stack-alignment fixes. The generic-call assertion correction is
already present in the base and is not part of the new change.

The measurements and bootstrap hash below describe the original development
snapshots. They are not a comparison between the published 0.1.12 release and
0.1.13. Verification of the port is recorded separately in
[nominal-resolution-0.1.13-validation.json](nominal-resolution-0.1.13-validation.json).

The port passes 33 focused checks in an offline Ubuntu 24.04 / Clang 18
container, including the existing callable, unit, plugin and node regressions.
Changed-source formatting and project `check` pass. Two independent
empty-cache `extreme` self-host builds from published 0.1.12 are byte-identical
and report `0.1.13-neumann`; the resulting compiler also passes the two new
standalone nominal-resolution regressions. A new native CI matrix has not run.

The previous typed lowering resolved every nominal spelling in the workspace
for every output module. An import-only Graphene module spent about 19 seconds
resolving types even though its EHIR contained no declarations to rename.
Import bindings were also repeatedly decoded during nominal lookup.

Lowering now collects the nominal spellings that the structural EHIR renamer
can visit and resolves only those candidates. The collector uses the renamer's
own traversal, including generic shadowing, method owners, field annotations
and symbol documentation. It reads the typed graph directly. Replacements
admit any later candidate they introduce, preserving substitution order.
Module-local import summaries retain decoded bindings in the original order,
including aliases, visibility and bare namespaces.

The focused workload lowers Graphene's `lib.enq` and `preview.enq` with stable
package ABI names. Three paired samples used the same frozen workspace,
bootstrap compiler and Clang `-O3`, with alternating order after the first pair.

| Focused measurement, median | Before | After |
|---|---:|---:|
| Lowering both modules | 31.292 s | 8.014 s |
| Process wall time, including workspace loading | 35.910 s | 12.747 s |
| `lib.enq` nominal resolution | 18.697 s | <0.001 s |
| `preview.enq` nominal resolution | 4.441 s | 0.098 s |

The lowering stage is 3.90x faster in this focused workload. Both serialized
EHIR module hashes are identical in all three pairs. This is a stage-level
measurement, not the speedup of a complete native build.

One matched pair of complete native builds used the same frozen Graphene
workspace, `dev` profile and eight build jobs. Each cold build started with an
empty project target and private compiled-artifact cache; dependency sources
were preseeded and the OS page cache was retained. Built-in phase timers were
enabled in both builds. No external profiler or resource caps were used.

| Full build measurement | Before | After |
|---|---:|---:|
| Complete cold native build | 542.141 s | 432.849 s |
| Unchanged native build | 6.823 s | 6.723 s |
| Graphene AST-to-EHIR lowering | 194.183 s | 87.578 s |
| Nominal resolution, sum across 258 modules | 105.816 s | 2.250 s |
| Function body lowering, sum across 258 modules | 77.573 s | 75.420 s |
| Graphene semantic checking | 65.621 s | 66.941 s |
| LLVM IR emission | 103.147 s | 103.039 s |

The complete cold build saves 109.29 seconds, a 20.16% elapsed-time reduction
(1.25x speedup). All 17 owning EHIR payloads, all 17 native language archives
and the executable are byte-identical; native camera, function and CLI probes
pass after cold and unchanged builds. Unchanged build times remain around
6.8 seconds. This single full-build pair is not a statistical performance
guarantee or a CI forecast. Module-level timing sums and package wall-clock
phases describe different scopes and should not be added together.

These comparisons use the preceding development head, `bd644e0`, rather than
published 0.1.11. Both measurement CLIs contain the production implementation
built as standalone CLI units by the same converged bootstrap compiler and
Clang 23 `-O3`. The full-build candidate snapshot precedes source formatting;
its implementation differs from the final source only in whitespace and
optional trailing commas. Self-host verification uses the final formatted
source separately.

The largest remaining measured stage is LLVM IR emission at approximately
103 seconds, followed by lowering at 87.6 seconds and semantic checking at
66.9 seconds. The remaining lowering time is predominantly function bodies.

Validation passed 28 focused checks: import and reflection identities,
generic scopes, function cache replay, direct typed lowering, independent AST
resolver comparisons, and all ten `ehir-core` tests. The standalone
`tests/nominal_type_resolution.enq` is discoverable by the normal repository
test command. An existing generic-call expectation also needed its mandatory
argument type: the old assertion failed on both `bd644e0` and the candidate.

Two independent empty-cache `extreme` self-host builds with Clang 18 and two
build jobs converged to SHA-256
`9dc5118fa69c9cedbc6410fde5b1b5ca630e52d4576bb119fdcdd47adc5a2ef0`.
The final standalone type-resolution and generic-call regressions also passed
when built by that self-hosted compiler.

Inputs, raw timings, phase profiles, artifact hashes and verification results
are in [nominal-resolution-2026-10-31.json](nominal-resolution-2026-10-31.json).

The fixture is [nominal_lowering/main.enq](../../tests/fixtures/nominal_lowering/main.enq).
`ENCORE_NOMINAL_BENCH_PROJECT` selects an existing frozen workspace. Its JSON
output reports workspace loading, lowering and serialized module hashes;
without that variable the fixture exits without running the workload.

# Planned safety inference: 2026-10-30

The safety solver formerly walked function bodies to collect dependencies and
walked them again during fixed-point iterations. Cold replay also collected
the same dependencies before entering that solver. Every traversal repeated
lexical callable/member resolution against the full semantic environment.

## Changes

Each function now compiles its existing conservative transfer rules into
temporary monotone OR formulas for `body_unsafe` and
`returns_unsafe_callable`. Known `safe` contracts mask the caller-visible unsafe
bit while retaining returned-callable effects. Closures, captures, assignments,
unknown calls, overload families, plugin proxies and implicit operator/iterator/
context-manager calls retain their previous behavior.

An arena shares intermediate formulas and flattens them iteratively into effect
references, avoiding recursive traversal or exponential expansion of shared
values. The worklist evaluates these references without revisiting syntax or
resolving declarations. Cold replay reuses the same prepared dependencies and
plans. Incremental SCC invalidation and fresh seeding of changed components are
retained, including unsafe-to-safe transitions.

Function-local name indexes read the actual callable/method views, including
generic overlays. They preserve first callable priority and method overload
order. Name filtering still delegates receiver matching and specialization to
the original semantic resolver. A checked `SemanticSlice.contains_index` query
avoids retaining full records during index construction. Native lookup handles
are freed before a finished plan leaves preparation; plans contain no mutable
database, syntax or lookup handles. No plan is persisted, and the replay schema
and effect ordering are unchanged.

The previous boolean AST interpreter remains available for the dependency query
and the independent full-scan regression oracle.

## Measurements

The [raw evidence](safety-inference-2026-10-30.json) records paired samples,
source/binary hashes, commands, CPU time, RSS and hashes of the complete effects
and replay payloads. The baseline includes the preceding **uncommitted shared
declaration preparation** on top of `11efe43`; this experiment isolates the
additional safety optimization.

Both native harnesses use the established e9 compiler and Clang 23.1.3 `-O3`
on the same Ryzen 7 7700 host. Each fresh process loads the same frozen Graphene
library workspace, prepares semantic environments and checks selected bodies
with eight workers before measuring cold `infer_safety_with_replay` with
`Json::Null`. Safety inference itself is serial. Both variants supply an empty
known-external-effects table; unresolved dependency effects remain conservative.
These are identical real checked function inputs, rather than a full package
worker's compiled dependency metadata representation.

The 28-module subset contains 627 functions and uses three alternating pairs.
All 221 library modules contain 3549 functions and use one pair, so that larger
result is preliminary. All selected bodies have zero diagnostics. Runs are
sequential without concurrent tests or a profiler; the OS page cache is retained.

Workspace/environment preparation and body checking are outside `safety_ms`
and inside whole-process wall time. Serializing/hashing the evidence after
inference is also inside whole-process time. Replay construction is inside
`safety_ms`. Only the cold safety phase is attributed to this optimization.

| Workload | Safety before | Safety after | Time reduction | Speedup |
|---|---:|---:|---:|---:|
| 28 modules, 627 functions, 3 pairs | 5.122 s | 0.411 s | 92.0% | 12.5x |
| All 221 library modules, 3549 functions, 1 pair | 92.579 s | 5.522 s | 94.0% | 16.8x |

Whole-process wall time falls from 13.892 s to 9.114 s for the subset and from
122.568 s to 35.616 s for the complete library set. Environment preparation and
body checking remain essentially unchanged. Full-set peak process RSS is also
essentially unchanged: 278.8 MiB before and 278.2 MiB after.

All eight effect snapshots and all eight replay snapshots match byte for byte
within their workload. All functions are cold checks with zero body diagnostics.
The complete-library pair saves 87.057 s in the measured safety phase.

## Validation and reproduction

All 12 selected regressions passed, including the existing independent full-scan
oracle. New tests exercise both formula outputs over truth tables, shared
subexpressions, 20,000-deep joins, construction-buffer release, exact dependency
ordering, closures/captures, imported overload effects, implicit calls, cold and
unchanged replay, first callable priority, Unicode names, projections, overlays
and malformed selection ordinals. Existing tests cover recursive and decreasing
effects, trusted factories, primitive operations, plugin proxy safety, prepared
package views and parallel checking. The dependency regression isolates safety's
binding rules and allows the existing lexical probe's local-callback name
diagnostics; the measured Graphene bodies have no diagnostics.

The entry point is
[`tests/fixtures/safety_inference/main.enq`](../../tests/fixtures/safety_inference/main.enq).
Compile it in frozen compiler source fixtures with the same seed and native
flags. Run each executable sequentially with `ENCORE_ENV_BENCH_PROJECT` pointing
to the same Graphene workspace. Omit `ENCORE_ENV_BENCH_ALL` for the subset; set
it to `1` for all library modules. Compare `safety_ms`, effect/replay hashes,
process wall time and RSS. Exact fixtures, commands and logs are retained under
`target/safety-0.1.12` and referenced by the JSON evidence.

A full Graphene native build and compiler self-host convergence have not been
rerun for this step. The earlier full-build safety timing is a different workload
and must not be substituted for this benchmark's baseline.

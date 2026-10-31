# Cold compilation of Graphene

The 0.1.12 work removes the fresh AST-to-text-to-EHIR round trip, shares
declaration and safety indexes, caches repeated namespace queries, and avoids
allocating a breadth-first search queue for common node owner checks. The
bounded depth-first owner search falls back to the complete search when its
scratch space is exhausted; reference counts and collection rules are unchanged.

The final optimization was measured against the preceding development compiler,
not the published 0.1.11 release. Each compiler built the same Graphene source
with an empty compiled-artifact cache, followed by an unchanged build.

| Measurement | Before | After |
|---|---:|---:|
| Complete cold native build | 1,070.17 s | 529.24 s |
| Unchanged native build | 6.78 s | 6.63 s |
| AST-to-EHIR lowering | 724.714 s | 190.658 s |
| `main.enq` function bodies | 216.829 s | 31.636 s |

This pair shows a 2.02x cold-build speedup (50.5% less elapsed time). It is one
before/after pair, not a statistical performance guarantee or a CI timing
forecast. Both measurement compilers use the production function bodies built
as standalone CLI units with the established e9 bootstrap compiler and Clang
`-O3`; these measurement builds do not establish self-host convergence.

All 17 owning EHIR payloads and all 17 native language archives were identical
between the measured versions. The executable changes because it contains the
optimized C node runtime. Native probes passed after both builds. Separate
native owner-search regressions compare reachability against an independent
oracle, cover the bounded-search fallback, and check the widely shared owner
case with AddressSanitizer and UndefinedBehaviorSanitizer.

The complete measurement inputs, hashes, phase timings, validation results and
limitations are in [lowering-2026-10-30.json](lowering-2026-10-30.json).
The preceding full-build profile is in
[graphene-native-2026-10-30.json](graphene-native-2026-10-30.json).
Earlier stages are documented in [direct EHIR construction](direct-ehir-lowering.md),
[semantic environments](semantic-environment-2026-10-30.md),
[semantic indexing](semantic-index-2026-10-30.md),
[semantic lookup](semantic-lookup-2026-10-30.md),
[semantic preparation stages](semantic-stages-2026-10-30.md), and
[safety inference](safety-inference-2026-10-30.md).

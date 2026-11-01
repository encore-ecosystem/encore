# Prepared namespace imports during AST-to-EHIR lowering

The baseline is `748fb08`, the converged 0.1.13 development compiler after
semantic name indexing. Its Graphene AST-to-EHIR phase takes 63.52 seconds,
the largest individual phase in the recorded 315.26-second cold build.

Namespace lookup cached complete query results, including misses, but every
new query still scanned the product of all source import paths and all imported
modules. Each pair called the general namespace resolver, which repeatedly
expanded grouped paths, parsed aliases and inspected target prefixes. In the
four-module diagnostic, only 292 uncached namespace queries caused 4,257,595
resolver calls. Their enclosing resolver took 9.47 seconds.

Each immutable export-syntax summary now prepares ordered namespace candidates.
It indexes imported module paths once, asks the existing conservative
`namespace_import_candidates` helper which targets can match each source path,
and restores the caller's original target order before retaining the selection.
Duplicate target spellings preserve their first occurrence, which is sufficient
because the final resolver depends only on the path text and target text.
Incomplete/editor paths retain the original complete target scan. Source path
order, private/public local imports, namespace aliases and prefix expansion
still use the original namespace resolver. Positive and negative query caching
retain their existing keys and lifetime.

Preparation occurs inside the measured AST-to-EHIR phase. The candidate plan
is local to the translation context's cached export summary, contains owned
strings and vectors, and is discarded with that context. It introduces no
process-global state, native pointers, runtime C or persistent cache-format
changes.

The complete native comparison uses the preceding semantic-name-index
iteration's baseline and a newly measured candidate on the exact same frozen
Graphene workspace path, source digests and dependency sources. Both use
converged `extreme` compiler binaries, Clang/LLD 23.1.3, the `dev` profile and
eight jobs. Each cold build starts with an empty target and private compiled
artifact cache. Dependency sources are preseeded and OS page cache is retained.
No compiler builds, tests or external profiler overlap either timed native run.

| Complete native build | Before | After |
|---|---:|---:|
| Cold build | 315.265 s | 301.089 s |
| Graphene AST-to-EHIR translation | 63.524 s | 52.808 s |
| Graphene semantic check | 43.556 s | 41.318 s |
| Graphene LLVM IR emission | 47.653 s | 47.595 s |
| Unchanged build | 6.370 s | 6.380 s |

The cold build saves 14.18 seconds, a 4.50% elapsed-time reduction. Graphene's
AST-to-EHIR translation takes 16.87% less time. All 17 owning EHIR payloads,
all 17 native language archives and the native executable match byte for byte.
Camera, ordinary-function and CLI probes pass after both cold and unchanged
builds. Unchanged builds remain around 6.38 seconds. Other phases also vary
between runs; the focused diagnostic supports attribution to namespace lookup.
This is one earlier baseline and one new candidate run, not a statistical
performance or CI guarantee. Package phase times overlap and must not be added.

The largest remaining individual Graphene phases are AST-to-EHIR translation
at 52.81 seconds, LLVM emission at 47.60 seconds and semantic checking at
41.32 seconds.

The matched diagnostic pair lowers Graphene's `main.enq`, `native_asset.enq`,
`animation/asset.enq` and `preview.enq` from the same frozen binary workspace.
Both executables use the same additional counters and Clang 23 `-O3`, with
counters reset after workspace loading. No compiler builds, tests or external
profiler overlap the measured runs. Operation durations are nested and must
not be summed. Serialization and output hashing occur after the lowering timer.

| Four-module diagnostic | Before | After |
|---|---:|---:|
| AST-to-EHIR translation | 36.979 s | 27.850 s |
| Whole process | 43.487 s | 34.288 s |
| Uncached namespace queries | 292 | 292 |
| General namespace resolver calls | 4,257,595 | 15 |
| Grouped-path expansion calls | 5,322,100 | 32,363 |
| Time inside uncached namespace resolution | 9.470 s | 0.000853 s |

Translation takes 24.69% less time, a 1.33x speedup in this diagnostic pair.
All four serialized EHIR hashes match exactly. The resolver timer excludes the
one-time candidate preparation, which remains included in translation time.
This is one diagnostic pair, not a statistical performance or CI guarantee.

The existing reusable entry point is
[ast_lowering/main.enq](../../tests/fixtures/ast_lowering/main.enq).
Set `ENCORE_AST_BENCH_PROJECT` to a Graphene workspace with available resolved
dependencies. It prints workspace and translation durations and serialized
EHIR hashes without the additional operation counters. Without the environment
variable it exits without running the workload.

All 14 selected internal translator contracts pass. The new ordered-scan
regression compares 1,200 query combinations across grouped/nested imports,
aliases, duplicate aliases, reordered and duplicate targets, Unicode strings,
wildcards, missing modules and incomplete syntax with the original sequential
resolver. The same regression passes with the newly self-hosted compiler.

Ten programs pass when compiled with the new compiler, covering grouped
imports, qualified generic/static calls, module/type scopes, direct typed EHIR,
callable names, function-cache reuse, nominal type resolution and import path
compatibility. A new standalone
[lowering_namespace_imports.enq](../../tests/lowering_namespace_imports.enq)
checks grouped imports, repeated namespace aliases, free-function calls and
nested type paths through the normal compiler driver, so this case remains in
the ordinary regression suite.

The changed translator source and standalone test have been formatted. Two
fresh empty-cache `extreme` self-host builds in Ubuntu 24.04 / Clang 18 Docker
produce identical binaries:
`769e7bac9593d433ce2af41f0dcd481641b655a30501819b7899600b19712e78`.
Their seed is the preceding converged development compiler at `748fb08`, not a
published 0.1.13 release. Native checks run on Linux x86_64 with Clang 23.1.3;
the new cross-platform CI matrix has not run.

Inputs, raw operation counters, complete native build timings, artifact
comparisons and verification are recorded in
[lowering-namespace-imports-2026-10-31.json](lowering-namespace-imports-2026-10-31.json).

# Shared semantic preparation

This change targets edited Graphene dev builds with a warm cache on `perf/hot-compilation-0.1.12`.
The target is at most 30 seconds in `semantic_prepare_ms`, with no increase in
maximum process RSS and an improvement in total frontend and native build time.

## Results

One matched pair per scenario; timings are preliminary under an external game workload.

| Edit | Baseline, s | Candidate, s | Time reduction |
|---|---:|---:|---:|
| Unchanged control | 7.214 | 6.206 | 14.0% |
| Method body | 229.972 | 100.478 | 56.3% |
| Function body | 280.939 | 140.876 | 49.9% |
| Three-line relocation | 253.917 | 124.914 | 50.8% |

The unchanged control takes the whole-unit cache path. Its single-pair difference
is treated as noise, not attributed to semantic preparation.

| Edit | Preparation before / after, s | Frontend before / after, s | Safety before / after, s |
|---|---:|---:|---:|
| Method body | 102.799 / 5.439 | 168.985 / 52.735 | 5.511 / 3.962 |
| Function body | 109.677 / 12.614 | 201.577 / 81.824 | 5.928 / 3.980 |
| Three-line relocation | 109.034 / 12.618 | 198.483 / 79.660 | 5.358 / 3.898 |

All three edited scenarios meet the 30-second preparation target. Their frontend
and native times improve; safety work is not inflated by environment rebuilding.

| Edit | Baseline max process RSS, GiB | Candidate max process RSS, GiB |
|---|---:|---:|
| Method body | 6.644 | 1.788 |
| Function body | 6.576 | 1.735 |
| Three-line relocation | 6.575 | 1.813 |

RSS is the `wait4` maximum for an individual process, not simultaneous process-tree
memory. Unchanged-control RSS is effectively equal (about 0.212 GiB).

| Active semantic payloads | Baseline, MB | Candidate, MB | Reduction |
|---|---:|---:|---:|
| Decoded bytes | 326.305 | 83.376 | 74.4% |
| Stored bytes | 104.558 | 18.649 | 82.2% |
| Allocated blocks | 105.288 | 19.472 | 81.5% |

Both caches have 380 module records; the candidate additionally references 17
shared snapshots. Decoded payload bytes are not an RSS measurement. The compiler
executable grew from 12.018 to 12.962 MB; semantic payload savings exceed 85 MB.

The first snapshot is still expensive: the excluded initial build took 829.847 s,
including 191.062 s of semantic preparation. About 185.6 s of that preparation
uses existing environment-resolution queries before interning. Declaration or
lookup-contract changes can rebuild the snapshot. Cold catalog construction
remains separate future work; these results target warm body/position edits.

## Data flow

Each package owns one `PackageSemanticIndex`. Declaration signatures, fields,
methods, enum variants and type bindings are interned into shared pools.
`ModuleSemanticView` retains ordered ordinals into those pools; callable aliases
have small binding records and share their declaration's parameter vectors.
The checker and safety inference retain `SemanticSlice` views, including small
local overlays for generic bound methods. They do not expand those views into
module-sized signature arrays. Existing vector-based analysis APIs use adapters.

The first snapshot is assembled using the existing declaration resolution rules.
This preserves import priority, overload families, private access, traits and
generic binders. Warm preparation restores the shared snapshot instead of
rebuilding these environments. The import graph has one adjacency index per
revision, and reachability traversals use checked ordinal edges and a visited set.
Context and dependency guard lookups use collision-checked string indexes.
The context also records unique qualified call names: changing `api::first()`
to `api::second()` invalidates stale bindings even with unchanged declarations
and reachability. Duplicate calls and source coordinates are omitted.

Workers receive immutable syntax facts from the completed source query, shared
declaration views and accepted body records. Parser state and the mutable
analysis database stay with the owner. `SemanticBodyPlan` selects cached facts
or a source check; the detailed type-scope index is created only on the first
body miss in that module. Current syntax supplies source coordinates, while
successful body facts can be relocated independently.

## Persistent identity and storage

A versioned binary package snapshot is stored through the existing verified,
compressed CAS and its locks. Small binary module records refer to the snapshot
and contain independently guarded body facts. The module namespace is
`encore-semantic-module-3`; old JSON module records are misses. Decode limits are
inherited from the bounded binary codec, and every selection ordinal is checked
before creating a view. Unknown, truncated or corrupt records rebuild from source.

Snapshot type tables store canonical HIR declaration keys. Dense `@N` references
are rebound through those keys when an existing database has a different load
order. Missing declarations discard the affected body facts. Type strings use
byte offsets, preserving Unicode. Implicit receiver records retain the operation
kind separately from the rebound receiver type; iterator, context-manager and
operator facts follow the same declaration table. Source positions do not define declaration
identity. Existing conservative barriers for layouts, imports, generics,
inferred/static/reflection bodies, cfg and manifest constants remain in place.
EHIR's typed representation and backend APIs are unchanged.

## Measurement protocol

The baseline compiler SHA-256 is
`7bff508c3f83f25baabb021de5fd5cc05965b5618db400fff13c8e77dbb96f99`.
The final candidate SHA-256 is
`3f017a53215da20cf4ca06548c747b9f162a36e934b6d36c0e3c4da72d6c034b`.
Two fresh `extreme` self-host builds of the frozen final source produced this
same candidate byte for byte, using separate empty compiled-package caches.

An attribution-only preparation probe, using the same real Graphene request and
old semantic cache, reduced preparation from 104.997 to 25.681 seconds. Context
work fell from 79.938 to 1.076 seconds; old cache reading still took 19.467 seconds.
This isolates the graph/context improvement and is not a native compilation
speed claim.

The native comparison uses one matched pair for each of: unchanged control,
method-body edit, ordinary function-body edit, and three-line relocation. Unique
priming edits are excluded. Successful frozen baseline samples are matched
against the final candidate by the exact source SHA-256 for every scenario.
The baseline and final candidate passes are not adjacent. Both variants use built-in phase timings, the same
SDK sources and frozen registry, and their own fixed workspace/cache paths.
There is no profiler library or CPU/RAM cap. The external game workload is
recorded as a source of noise; these are preliminary single-pair measurements.
Headless native probes check the changed method and function after every build.
A later empty-cache build must match the incremental native binary byte for byte.
Cross-workspace binary equality is not a requirement: six C vendor `__FILE__`
strings contain the different workspace roots and affect linked addresses. An
initial protocol attempt stopped on that overstrict check and is excluded.

Raw artifacts are under `target/semantic-pipeline/`: `progress.json`,
`graphene-native-result.json`, `bootstrap-e.json`, `relevant-tests-e.json`,
`result-logs/` and the frozen compiler/workload sources. Cache accounting counts
current module slots and exactly their referenced shared snapshots, excluding
unrelated object, EHIR and link history.

All 63 selected regressions and native cache/parallel integration contracts
passed. Added tests cover shared selection ordering, binary corruption and
truncation, graph invalidation, visibility/generic/trait parity, different module
load order, Unicode, rebinding implicit and generic-bound receivers, and
unchanged syntax/catalog data after parallel checks. The iterator rebinding
regression was observed failing before its fix and passing afterwards.

Native probes passed after every measured build. An empty-cache native build
matched the incremental binary byte for byte:
`acd399eae356237fac0cac46368f0d543cfa6c8a7a0c77a5d0f7159980c6cc5e`.

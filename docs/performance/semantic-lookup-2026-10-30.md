# Function lookup and method preparation: 2026-10-30

Function namespace resolution formerly tested every import against every module
in the semantic graph. It now extracts candidate module paths from each import
and looks them up in the existing module index. Candidate positions are checked
in graph order, preserving priority for ambiguous grouped aliases. The original
alias resolver still validates each match; explicit workspace resolution edges
retain their existing priority. Incomplete groups or unusual whitespace in
editor import text conservatively retain the old graph scan.

Method preparation now builds one type-name index per collection instead of
repeatedly scanning type-name bindings. An impl's trait owner is resolved once
per nonempty impl, rather than once per method. Indexed type scoping retains
generic binder, local scope and prelude precedence. Visibility preparation skips
replacing records that are already public, avoiding redundant graph-edge
updates. Private method signatures keep their existing visibility hash.

Additional preparation counters separate callable definition-map access,
declaration collection, binding selection and qualified lookup, plus method
collection, visibility, inheritance and scope normalization. They are exposed in
frontend timing output and the standalone benchmark fixture. Persistent semantic
cache schemas and lookup behavior remain unchanged.

## Measurements

The [raw evidence](semantic-lookup-2026-10-30.json) records samples, detailed
counters, CPU time, RSS, native commands, source/binary hashes and snapshot
hashes. The baseline includes the preceding **uncommitted typed-index
optimization**, documented in
[the shared-index experiment](semantic-index-2026-10-30.md), on top of commit
`5491426`. Both variants have identical timing instrumentation. This isolates
the additional benefit of namespace lookup and method preparation.

Both native harnesses use the established e9 compiler and Clang 23.1.3 `-O3`
on the same AMD Ryzen 7 7700 host. Every measured process creates a fresh
analysis database and prepares the same isolated Graphene library workspace
without persistent semantic replay. Runs are sequential, without concurrent
tests or a profiler; the OS page cache is retained. Loading the workspace,
preparing its package identity and encoding the resulting snapshot are outside
preparation timing and inside process wall time. Fixture test-annotation
adjustments and exact source comparisons are recorded in the JSON evidence.

The subset takes every eighth library module, giving 28 modules. It uses three
alternating baseline/candidate pairs and reports medians. All 221 library
modules use one pair, so the larger result is preliminary.

| Workload | Phase | Before | After | Time reduction |
|---|---|---:|---:|---:|
| 28 modules, 3 pairs | Callable discovery/resolution | 2.804 s | 0.035 s | 98.8% |
| 28 modules, 3 pairs | Method preparation | 2.256 s | 0.892 s | 60.5% |
| 28 modules, 3 pairs | Complete semantic preparation | 9.227 s | 5.071 s | 45.0% |
| All 221 library modules, 1 pair | Callable discovery/resolution | 25.362 s | 0.318 s | 98.7% |
| All 221 library modules, 1 pair | Method preparation | 19.292 s | 7.945 s | 58.8% |
| All 221 library modules, 1 pair | Complete semantic preparation | 68.855 s | 32.588 s | 52.7% |

Complete-library preparation saves 36.267 s. Whole-process wall time falls from
74.963 s to 38.699 s, including workspace loading and snapshot encoding. Peak
process RSS is essentially unchanged: 1,739.5 MiB before and 1,740.7 MiB after.
All eight snapshots match byte for byte within their workload, including the
same complete-library snapshot as in the preceding shared-index experiment.

Detailed counters locate the gains: qualified callable lookup falls from
25.257 s to 0.230 s; method collection from 11.651 s to 3.971 s; visibility
updates from 4.055 s to 0.378 s. Inheritance traversal (0.223 s to 0.228 s) and
method signature normalization (3.343 s to 3.344 s) are essentially unchanged.

## Validation and reproduction

All 18 selected semantic/database regressions passed. After adding conservative
handling of import paths ending in `::`, the namespace regression was rerun and
passed again; final benchmarks include this guard. New tests compare
candidate-based namespace resolution with the previous graph-scan oracle across
bare, aliased, grouped, nested, wildcard, Unicode and incomplete import text.
They also check duplicate alias priority and database edits. A separate method
test checks generic trait contracts, inherited members, public/private methods
and invalidation after editing the parent trait. Existing coverage includes
qualified callable aliases, namespace query invalidation, receiver/method
generics, plugin proxy safety, parallel views and semantic-index persistence.

The benchmark entry point is
[`tests/fixtures/semantic_environment/main.enq`](../../tests/fixtures/semantic_environment/main.enq).
Compile it as a standalone test in frozen source fixtures using the same seed
and native flags. Then run each executable sequentially with
`ENCORE_ENV_BENCH_PROJECT` pointing to the same isolated Graphene project.
Omit `ENCORE_ENV_BENCH_ALL` for the subset; set it to `1` for all library
modules. Compare `callables_ms`, `methods_ms`, `prepare_ms`, process wall time
and `snapshot_sha256`. Frozen fixtures, commands and logs are retained in
`target/semantic-lookup-0.1.12` and referenced by the JSON evidence.

This experiment measures semantic preparation. A full Graphene native build and
compiler self-host convergence have not been rerun for this step.

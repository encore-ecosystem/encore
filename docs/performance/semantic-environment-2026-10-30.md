# Semantic environment preparation: 2026-10-30

The compiler prepares each module's semantic environment before parallel body
checking. This change reduces repeated lookup work in that serial stage. The
persistent semantic index, module and function cache formats remain unchanged.

## Changes

- Index nominal types by their complete HIR keys instead of scanning the type
  table for every binding. Preserve insertion order and rebuild the lookup index
  when replay installs or extends the ordinal table.
- Read module fingerprints and source names through the existing module index.
  Checking a cached definition map no longer walks owning source records and
  retains/releases their AST references. Read cache candidates as borrowed values.
- Remember namespace resolution results, including misses, by calling module,
  requested namespace and database revision. Source/import-resolution changes
  invalidate the results. Repeated associated calls no longer repeat the same
  unsuccessful module lookup.
- Select core prelude module names without iterating owning source records.
- Expose environment preparation subphases through normal `--timings` output.
  Type-index construction is included in the names phase; callable type scoping
  is included in the callables phase. These nested diagnostics are not additive.

## Measurements

The [raw evidence](semantic-environment-2026-10-30.json) records inputs, hashes,
toolchain, samples, CPU time, peak RSS and semantic snapshot hashes. Both native
standalone harnesses were built with the established 0.1.12 e9 compiler and the
same Clang 23.1.3 `-O3` wrapper. The baseline is commit `3e25578` with subphase
timers added. Preparation is serial, using an AMD Ryzen 7 7700 with 16 available
logical CPUs. No profiler or concurrent verification workloads were active.

Each sample loads the same isolated Graphene library workspace into a fresh
analysis database, computes the package identity, prepares environments without
persistent replay, then encodes and hashes the semantic snapshot. Workspace
loading, identity preparation and snapshot encoding are outside `prepare_ms`
and inside the measured process wall time. OS page cache is retained.

The subset selects every eighth library module, giving 28 modules spread across
the project. Three sequential pairs alternate order. The complete library set
contains 221 modules and has one pair, so that larger result is preliminary.

| Workload | Pairs | Preparation before | Preparation after | Time reduction | Process wall before | Process wall after |
|---|---:|---:|---:|---:|---:|---:|
| 28 library modules | 3 | 14.190 s | 10.249 s | 27.8% | 19.627 s | 15.615 s |
| All 221 library modules | 1 | 104.258 s | 77.627 s | 25.5% | 110.415 s | 83.682 s |

Values for the subset are medians. The complete-library pair saves 26.631 s in
preparation. Peak process RSS is 1,745.2 MiB before and 1,746.0 MiB after.

| Complete-library phase | Before | After |
|---|---:|---:|
| Type names and their lookup index | 19.614 s | 5.696 s |
| Visible callables and type scoping | 36.235 s | 24.636 s |
| Fields | 3.612 s | 3.522 s |
| Methods | 19.530 s | 19.377 s |
| Aggregate/constructor selections | 6.348 s | 5.756 s |
| Shared package-index assembly | 13.349 s | 13.059 s |

Every snapshot matches byte for byte between variants and repetitions within
its workload. The remaining largest costs are callable discovery, method
collection and package-index assembly.

## Validation and reproduction

All 19 selected semantic/database regressions passed. New regressions cover
qualified overloads, local shadowing, re-exports, source changes, retained
definition lifetimes after module removal, nominal-table restoration/extension,
and invalidation of namespace hits/misses after import-resolution changes.

The standalone harness is retained at
[`tests/fixtures/semantic_environment/main.enq`](../../tests/fixtures/semantic_environment/main.enq).
To reproduce, copy it to `tests/environment_benchmark.enq` in isolated baseline
and candidate compiler source fixtures, compile it with the same seed compiler
and native optimization flags, and run each resulting executable sequentially.
Set `ENCORE_ENV_BENCH_PROJECT` to the same Graphene library workspace and set
`ENCORE_ENV_BENCH_ALL=1` for the complete module set; omit the latter for the
subset. Use the same local SDK and registry sources for both variants. Without
the project variable the harness exits without measuring, allowing compilation
to be separated from timing. The JSON evidence links the exact build inputs,
binary hashes, original commands and per-run logs retained under `target`.

This benchmark isolates semantic environment preparation. Its module set and
source-based dependency representation differ from the earlier full Graphene
binary build, so its 104 s baseline must not be compared directly to that build's
185 s environment phase. Full Graphene compilation and compiler self-host
convergence have not been rerun for this step.

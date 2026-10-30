# Shared semantic index assembly: 2026-10-30

`SemanticIndexBuilder` formerly created JSON arrays and strings for every
declaration, binding, field, method, enum variant and type-name binding before
deduplicating them. This repeated allocation and formatting for records shared
by many module environments.

The builder now interns typed records directly. The construction table stores
canonical records, cached 64-bit hashes and open-addressed ordinal slots. Hash
matches are checked with exact equality of every field in the former JSON key,
including ordered parameter/generic lists, visibility, signatures and binding
identities. Table growth reuses hashes and preserves first-insertion ordinals.
No serialized representation is constructed for lookup.

The completed index retains its existing arrays and schema. Construction-only
hashes and slots are discarded; persistent cache formats remain unchanged.

## Measurements

The [raw evidence](semantic-index-2026-10-30.json) contains source/binary hashes,
native build commands, CPU time, RSS, samples and semantic snapshot hashes.
Baseline: commit `5491426`, immediately after the preceding environment lookup
optimization. Its verified native benchmark binary was reused after checking
that all compiler source files matched the frozen baseline fixture.

Both harnesses use the established 0.1.12 e9 compiler and Clang 23.1.3 `-O3`, on
the same AMD Ryzen 7 7700 host. Each process creates a fresh analysis database,
loads the same isolated Graphene library workspace, prepares environments
without persistent replay, and encodes/hashes the resulting semantic index.
Runs are sequential, without concurrent tests or a profiler. OS page cache is
retained. Workspace loading, identity preparation and snapshot encoding are
outside preparation timing and inside total process wall time.

The subset selects every eighth library module, giving 28 modules. Three pairs
alternate baseline/candidate order; displayed values are medians. The complete
library set has 221 modules and one pair, so that larger result is preliminary.

| Workload | Index before | Index after | Index time reduction | Preparation before | Preparation after | Preparation time reduction |
|---|---:|---:|---:|---:|---:|---:|
| 28 modules, 3 pairs | 1.534 s | 0.411 s | 73.2% | 10.425 s | 9.394 s | 9.9% |
| All 221 library modules, 1 pair | 13.312 s | 3.488 s | 73.8% | 79.409 s | 69.330 s | 12.7% |

The complete-library preparation saves 10.079 s. Whole-process wall time falls
from 85.467 s to 75.440 s, including index finalization and snapshot encoding.
Peak process RSS falls from 1,747.2 MiB to 1,740.9 MiB.

All eight snapshots match byte for byte within their workload. The index now
accounts for about 5% of complete-library environment preparation; callable
discovery and method collection remain the largest measured components.

## Validation and reproduction

All 13 selected semantic/database regressions passed. New tests independently
compare typed record equality and interning against linear lookup of the former
JSON keys, varying each record field and covering list boundaries, Unicode,
control characters, local aliases and module selection order. A separate test
forces every record to the same hash, exercises growth/reverse replay and
checks that graph-managed construction storage is released.

Existing tests cover cache encode/decode and replay, declaration lifetimes,
nominal table restoration, qualified calls, namespace invalidation, visibility
and parallel/shared views.

Reuse the standalone harness at
[`tests/fixtures/semantic_environment/main.enq`](../../tests/fixtures/semantic_environment/main.enq)
and the [preceding preparation protocol](semantic-environment-2026-10-30.md).
Copy it into isolated compiler source fixtures, compile both with the same seed
and native optimization flags, then run them sequentially against the same
`ENCORE_ENV_BENCH_PROJECT`. Set `ENCORE_ENV_BENCH_ALL=1` for all library modules;
omit it for the subset. Compare `index_ms`, `prepare_ms`, process wall time and
`snapshot_sha256`. Exact commands, frozen inputs and logs are retained under
`target/semantic-index-0.1.12` and referenced by the JSON evidence.

This experiment measures semantic preparation. A full Graphene native build and
compiler self-host convergence have not been rerun for this step.

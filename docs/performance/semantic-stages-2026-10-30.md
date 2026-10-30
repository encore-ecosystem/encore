# Shared declaration preparation: 2026-10-30

The baseline is commit `11efe43`, after the shared-index and namespace/method
lookup optimizations. This step addresses the remaining names, fields, methods,
aggregate/constructor and index phases together.

## Changes

A preparation cache exists only during one immutable package preparation pass.
Type declarations, the core prelude, fields and method declaration groups are
collected once per declaring module and shared across consumer environments.
Local type display names remain specific to each consumer. Normalized field
and method records are reused by exact raw declaration identity. Their lexical
type scope is invariant across consumers within this pass. The cache is
discarded before another preparation, source edit, replay or nominal rebinding;
it never becomes a persistent cache or a worker-owned mutable object.

Package preparation consumes each temporary environment immediately instead of
also retaining a full compatibility environment for every consumer until the
end. Only the current consumer's type-name vector is retained for the next
query in the same iteration. Editor queries retain their ordinary revision
caches. Cache scans read borrowed module/revision fields before returning a
matching value.

Aggregate selection now uses a string set while preserving the original
first-insertion order. Method groups retain declaration order, visibility,
generic binders and trait inheritance; plugin proxies are still constructed
using the current consumer's reachable plugin types.

Record interning uses existing declaration signatures as hash hints instead of
rehashing every signature string and parameter list. Type-name hashes omit
presentation fields. Equality still checks **every field** of the old keys;
matching signatures or hashes never suffice to merge records. Hash accumulation
updates a local scalar rather than a mutable record for every byte. Stable
ordinals and the serialized semantic-index schema are unchanged.

## Measurements

The [raw evidence](semantic-stages-2026-10-30.json) records source/binary hashes,
native commands, detailed counters, CPU time, RSS and semantic snapshots.
Both baseline and candidate have identical additional timing counters and use
the established e9 seed with Clang 23.1.3 `-O3` on the same Ryzen 7 7700 host.
Test annotations are removed from both frozen source fixtures to avoid unrelated
embedded tests; all candidate function bodies match the working tree.

Each measured process creates a fresh database, loads the same isolated Graphene
library workspace, and prepares environments without persistent semantic replay.
Workspace loading, package identity preparation and snapshot encoding are outside
preparation timing and inside whole-process wall time. Runs are sequential,
without concurrent tests or a profiler; the OS page cache is retained.
The 28-module subset uses three alternating pairs; all 221 library modules use
two alternating pairs. Reported values are medians.

| Phase, all 221 library modules | Before | After | Time reduction |
|---|---:|---:|---:|
| Names and type-name index | 5.686 s | 2.083 s | 63.4% |
| Fields | 3.491 s | 0.747 s | 78.6% |
| Methods | 7.850 s | 2.063 s | 73.7% |
| Aggregates and constructors | 5.608 s | 0.321 s | 94.3% |
| Shared semantic index | 3.457 s | 1.320 s | 61.8% |
| Complete semantic preparation, including cleanup | 31.918 s | 11.624 s | 63.6% |

Method declaration collection falls from 3.936 s to 0.738 s and method
normalization from 3.281 s to 0.693 s. Aggregate deduplication falls from
5.373 s to 0.070 s. Callable preparation is essentially unchanged
(0.309 s to 0.311 s); enum payload preparation varies from 0.558 s to 0.632 s.

On the 28-module subset, complete preparation falls from 4.983 s to 2.755 s
(44.7%). Whole-process wall time falls from 10.401 s to 8.072 s for the subset
and from 38.026 s to 17.615 s for all modules. Complete-library peak process RSS
falls from 1,740.6 MiB to 303.5 MiB (82.6%).

All ten snapshots match byte for byte within their workload, including the same
snapshot hashes as the preceding lookup experiment. These results isolate this
step's benefit relative to `11efe43`; reductions from earlier reports should not
be added arithmetically.

Additional counters explain the former unmeasured interval: the baseline spends
about five seconds clearing the accumulated compatibility caches at the end.
The candidate clears much smaller caches there and releases temporary environments
during individual module iterations. These costs are included in complete
preparation time; the decrease in the final cleanup counter is **not** an
independent five-second saving that can be added to other phase improvements.
In the final full-library pairs, final cleanup is 4.941 s before and 0.024 s
after. About 4.1 s of the candidate's total preparation is outside the narrow
phase counters but inside per-module scope and loop timings; this includes
temporary ownership/cleanup overhead. It remains part of the reported 11.624 s.

## Validation and reproduction

All 23 selected semantic/database regressions passed. The new preparation test
compares the complete encoded package index with independently prepared editor
environments that bypass package sharing. It covers two consumers with different
aliases and local names, generic fields and methods, core-prelude shadowing,
enum constructors, repeated preparation, reversed consumer order, source edits,
module removal and restoration. Existing tests cover private/inherited methods,
plugin proxy safety, type identity, qualified imports, parallel/shared views,
semantic replay, ordinal-table restoration and collision-checked interning.

The standalone entry point is
[`tests/fixtures/semantic_environment/main.enq`](../../tests/fixtures/semantic_environment/main.enq).
Compile it in isolated source fixtures with the same seed and native flags.
Run each executable sequentially with `ENCORE_ENV_BENCH_PROJECT` pointing to the
same Graphene workspace. Omit `ENCORE_ENV_BENCH_ALL` for the subset; set it to
`1` for all library modules. Compare phase counters, `prepare_ms`, wall time,
RSS and `snapshot_sha256`. Frozen sources, logs and driver scripts are retained
under `target/semantic-stages-0.1.12` and referenced by the JSON evidence.

This experiment measures semantic preparation. A full Graphene native build and
compiler self-host convergence have not been rerun for this step.

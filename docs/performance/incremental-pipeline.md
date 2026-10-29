# Incremental package compilation

The compiler reuses work across ordinary `encore build` invocations. No resident
compiler process is required. Package metadata is verified before it becomes an
input to another package; ordinary dependency bodies remain private.

```mermaid
flowchart LR
    A[Current declarations and imports] --> B[Validate scoped environment]
    B --> C[Replay unchanged body facts]
    C --> D[Check missing bodies]
    D --> E[Update safety components]
    E --> F[Replay lowered fragments]
    F --> G[Look up prepared objects]
    G --> H[Emit LLVM IR for misses]
    H --> I[Compile misses and link]
```

## Frontend records

A module record contains successful function-body facts, their dependency
guards, and a shared scoped environment. The full context binds declaration
contracts, import reachability, package constants, target/features, and the
source identities used for nominal types. An unchanged context permits replay
of the environment without rebuilding its callable and member tables.

On a changed context, callable lookup-family guards validate individual bodies.
Unrelated ordinary function declarations do not invalidate independent bodies.
Layouts, imports, trait/impl contracts and compile-time template changes remain
conservative barriers. Failed lookups bind the complete visible declaration
context. Reflection/decorator bodies retain their normal checking path.

Successful declaration/name-resolution checks are replayed only when the
complete module source and context both match. An unsuccessful result cannot
suppress a later diagnostic. Parsing and current declaration inputs still come
from the current workspace.

Body identities include the exact owning source lines and a location-independent
AST identity. Moving a function preserves its key; editing its internal layout
can cause a miss. Replayed lexical positions are rebased onto the current
declaration. Failed checks are not stored. Unchanged successful module records
are touched on read rather than rewritten.

## Effects and native objects

Safety records retain resolved edges and both internal and caller-visible
effects. Changed strongly connected components start from the solver's initial
state. Components run callee-first; unchanged caller-visible effects stop
propagation. The full solver remains the regression oracle.

Prepared object keys bind normalized owned EHIR, declarations/templates,
specialization/layout requirements, compiler identity, target and native tools
with flags. They are available before LLVM emission. An alias points into the
existing object CAS; the object is copied and verified under its own lock.
Missing or corrupt aliases and objects are misses. Global support definitions
remain separate from ordinary package objects.

Semantic and IR threads borrow nonblocking leases from the same jobserver as
package and native-tool workers. All threads join before their extra leases are
released. Target state is installed in every IR worker, and result publication
retains canonical module order.

## Storage and measurement

Frontend records and object aliases use the existing verified packed-entry
store and its locks, accounting and pruning. Record kinds have separate key
prefixes; existing object payloads are not duplicated. Compiler identity bounds
semantic replay compatibility.

Package timing reports include `bodies_checked`, `bodies_reused`,
`environments_reused`, `effects_checked`, `effects_reused`, `ir_generated` and
`ir_skipped`. `module_checks_reused` counts unchanged successful module checks.
`semantic_prepare_ms`, `semantic_bodies_ms`,
`semantic_publish_ms`, `object_probe_ms` and `ir_emit_ms` distinguish preparing
inputs from checking bodies and emitting IR. Worker counts are reported as
`semantic_jobs` and `ir_jobs`.

Use the [Graphene protocol](hot-compilation-protocol.md) for performance claims.
Warm-ups, profiling and diagnostic builds do not belong in paired medians.

# Compiler Logic

This chapter describes the frontend analysis database and the mandatory typed
EHIR boundary used by preparation and code generation. Type inference belongs
to the Encore frontend; EHIR never contains values awaiting type propagation.

## Incremental Frontend Database

The compiler, checker, linter, formatter and language server share the typed
`AnalysisDatabase`. A module is interned under a deterministic `ModuleId`, and
its declarations receive deterministic `SymbolId` values derived from the
module identity, declaration kind, name and overload ordinal. These canonical
keys are stable across database instances and are suitable for future on-disk
module caches.

The database keeps independent tolerant and strict queries:

- the lightweight query supplies tokens, declarations, imports and diagnostics
  while an editor buffer may be incomplete;
- the full query supplies the parsed AST required by the compiler and analyzer;
- the lossless syntax query retains whitespace, line endings and every comment
  for formatting and source transformations, and is computed only on demand;
- compiler workspace ingestion uses `set_module_full`, so valid build input is
  lexed and parsed only once.

Every source update receives a revision, except an update whose path and
contents are unchanged. The declaration interface has its own fingerprint and
revision. Function bodies are omitted from this fingerprint, so editing an
implementation invalidates that module's full query but preserves cached
queries for importers. Changing a signature, type declaration, import or other
interface token invalidates transitive dependants through the module graph.

Query counters are exposed for behavioral tests. Incremental behavior is
therefore verified by proving that an unaffected query was not recomputed,
rather than only comparing its returned value.

The formatter consumes the lossless query and existing frontend diagnostics.
It never writes invalid input, returns an unchanged result on errors and is
idempotent. The CLI and LSP use this same formatting implementation.

### Function semantic queries

Semantic analysis is also cached at function-body granularity. A
`SemanticBody` is addressed by the declaration's stable `SymbolId` and stores
inferred local binding types, structured diagnostics, and the callable
signatures read while checking the body. Its cache entry is validated against
both a fingerprint of that exact body and fingerprints of those signatures.

Consequently, changing one function body does not recompute neighbouring
functions, including same-named methods in different `impl` scopes. Changing
an imported function signature invalidates bodies that called that declaration
without invalidating unrelated bodies in the importing module. Semantic errors
are returned as `FrontendDiagnostic` values; compiler checking can stop before
EHIR lowering without terminating from inside the query.

The semantic result models primitive literals, local bindings, explicit
binding annotations, assignments, returns, conditions, nested control flow,
binary results, casts and direct function calls. Declaration checks, call
arity, return types and body diagnostics are emitted through the same query.
Additional language forms must extend this result rather than introduce a
second type model in the compiler or language server.

## Mandatory EHIR Types

Every canonical `Variable` carries a required `Type`, including its generic
arguments and value/node representation. Instruction constructors cannot accept
an absent value type. `FieldSelector` is separate metadata, while enum tags and
the unit literal have explicit value kinds.

The text parser requires a type on instruction results. It may bind an operand
without an annotation to an existing typed definition in the function's SSA
scope. Standalone instruction parsing requires operand annotations. Explicitly
typed forward references, such as a loop phi input, are checked against all
function definitions during validation. No instruction-rewriting type recovery
pass follows parsing.

Validation checks SSA definition uniqueness, undefined references and exact
type agreement with their definitions, along with operation and control-flow
constraints. A decoded prepared-function artifact goes through the same SSA
validation before reuse.

`PreparedProgram` holds the canonical `ModuleBundle` directly. Preparation,
function caching and LLVM share this graph rather than freezing it into indexed
records and thawing it again. Indexed `TypedProgram` conversion remains an
optional export API; it is outside the main compilation pipeline.

## Value And Node Representations

EHIR preserves the representation of every type. For payload `T`, the
forms `T`, `T<S>`, `T<H>`, `T&` and `T*` are different types:

- `T` is an inline value;
- `<S>`, `<H>` and `&` are owning node handles;
- `*` is an unsafe raw address.

`T<S>` and `T<H>` can satisfy a `T&` parameter without changing the one-word
runtime ABI. The reverse conversion requires placement proof. `T*` never
satisfies `T&`.

Mutability is not represented by a pointer kind. Encore initially lowers local
bindings to local-cell operations. A dedicated pass resolves mutable aliases
and promotes those cells to SSA values and phi nodes.

## Canonical Function Pipeline

EHIR functions begin as graph-transforming state machines with one entry and
possibly several normal returns. Compilation uses this fixed pass order:

1. receive typed declarations and instructions from the frontend;
2. monomorphize concrete functions and lifecycle descriptions;
3. convert local cells and mutable aliases to SSA;
4. normalize every normal return into one typed exit phi and one `ret`;
5. lower coroutine suspension, then normalize generated functions again;
6. infer `T&` escape effects and validate stack-node regions;
7. compute CFG liveness and lower implicit ownership to explicit operations;
8. synthesize structural value helpers and node descriptors;
9. validate canonical ownership, CFG and types;
10. lower the validated module to a backend dialect.

The unique exit is represented with a phi value rather than an alloca. This
keeps mutable source constructs out of the backend and prevents loop-lifetime
temporaries from accumulating in one generated stack frame.

`unreachable` is an abnormal terminal assertion and is not counted as another
normal exit.

## Ownership Lowering

Encore does not insert ad-hoc retain/drop sequences while translating syntax.
The EHIR ownership pass operates on the complete typed CFG and handles:

- inline structural copy and move;
- node-handle acquire, transfer and last use;
- arguments and return values;
- phi edges, matches, loops and early returns;
- field reads and transactional replacements;
- initialized container elements.

A source value may be moved instead of retained when liveness proves its owner
ends at that transition. The pass emits `cfree` for the last use of a node
handle and structural `drop` for inline values. The LLVM backend does not infer
ownership from names, library types or source constructs.

## Escape And Effect Analysis

Each `T<S>` carries its allocating frame region. The analysis rejects any path
which can retain that node after the frame exits, including returns, heap or
global stores, thread transfer and coroutine suspension.

A body-defined `T&` parameter receives an inferred escape summary. An extern
parameter needs an explicit `noescape` contract before a stack node can be
passed. Returning an alias and storing a handle are distinct effects and are
part of the function signature used by incremental semantic queries.

## EHIR Validation Boundary

The backend accepts only canonical EHIR. Validation proves:

- one entry and one normal exit;
- exact field, call and phi types;
- no use after ownership transfer or drop;
- no owner leaked from a normal path;
- no invalid stack escape;
- no safe raw-memory copy of an owning value;
- lifecycle metadata for every concrete node payload.

Diagnostics retain their original Encore `SourceSpan`; parsing a serialized
EHIR cache must preserve the same location metadata.

## Why This Matters

Mandatory EHIR types do not by themselves establish memory safety. SSA, region validation, ownership lowering and ERN runtime
semantics are separate required proofs. A source program passing `encore check`
cannot bypass any of them when it is built.

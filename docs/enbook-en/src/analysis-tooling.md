# Analysis and tooling architecture

Encore source tooling is built around one demand-driven semantic database.
The compiler, `encore check`, `encore lint`, the formatter, LSP, and IDE clients
must not implement separate name-resolution or type systems.

The semantic pipeline is:

1. lossless per-file syntax and parsed AST;
2. a project module graph and per-module definition map;
3. semantic HIR with stable module, definition, body, expression, and type IDs;
4. name resolution, type inference, trait obligations, and control-flow facts;
5. structured diagnostics, lint findings, formatting, and IDE queries;
6. EHIR lowering and backend code generation.

The shared query layer performs fast, structured checks first. Checks which
still depend on the mature lowering validator (including some ownership,
generic-bound, async, and exhaustive-match rules) run through a
validation-only translation pass which discards EHIR output. This preserves
complete compiler behaviour while those checks migrate into reusable queries.

The separately distributed LSP remains a thin JSON-RPC transport adapter over
the compiler's public analysis database, formatter, lint engine, project
configuration, ranges, and suggestions; it does not contain a second language
analyzer.

Worker-side syntax validation retains its recovered AST. The database reuses
that immutable result when a semantic query first requests the full document,
instead of discarding it and parsing the same tokens again. Persistent
declaration-only cache entries still parse on demand; their `parsed` flag is
not treated as proof that they contain an AST. Retained nodes keep the physical
source path for diagnostics even when the module has a different logical name.

Changing a function body must not invalidate unrelated module interfaces.
Changing a public signature invalidates only queries which read that
definition. Query outputs are immutable values and do not perform filesystem
I/O, which permits future parallel evaluation and persistent caching.

Cursor queries reuse cached function-body results before constructing the
visible callable/member environment. Reuse still validates recorded dependency
signatures, including inherent methods; a changed signature must refresh inferred
binding types even when the caller's text is unchanged.
Within an unchanged database revision, an already validated body is reused
without repeating its dependency checks. Visible field and method environments
are also cached per module and revision. Removing a module releases these
environments; edits still trigger dependency validation before reuse.

Reference searches prepare each document's import graph once per batch and
resolve candidate identities without constructing member hover documentation.
Named member queries specialize only matching declarations; completion uses
the same query with no name filter to list all eligible members.

Inferred local type hints use the same scoped binding facts as hover and
navigation. The LSP does not guess an initializer's type from its first token
or carry bindings between unrelated lexical scopes. Explicit annotations are
not duplicated. Hint queries respect the requested UTF-16 range and analyze
only bodies containing eligible declarations in that range.
Callable environments come from the module's resolved value namespace, including
aliases and public re-exports, rather than every function in every imported file.
Cached calls track both the original signature and the local binding's target ID;
redirecting a re-export invalidates its callers even if the old declaration remains.

Failed lookups also record a dependency on the visible declaration scope. Adding
a previously missing function, field or method therefore retries the query without
requiring an edit to its caller. This dependency is broader than a successful
signature lookup, but excludes unrelated modules and body-only edits to dependencies.

Local rename checks simulate the new name against the same lexical binding
lookup used for navigation. They reject edits which redirect a reference or
capture an existing name; names in independent scopes remain independent.
This simulation does not mutate source files or cached semantic results.
For clients supporting versioned workspace edits, rename includes the current
version of each open document so an outdated edit can be rejected by the editor.

An explicit import alias has a separate rename identity from its underlying
declaration. Go-to-definition still reaches the original declaration, while
renaming the original preserves alias names and renaming an alias preserves
the original. Public re-exports carry this distinction through the module graph,
including aliases with the same spelling as their source name.

Member completion uses receiver types recorded during expression analysis,
including function and method results, array indexing, tuple fields and
parenthesized expressions. The editor parser retains the receiver of an
unfinished `expression.` with a missing-member diagnostic; strict compilation
still rejects the unfinished expression. The LSP does not reconstruct receiver
types by splitting a textual chain of names.

Member navigation uses the same receiver query and carries the declaring module
and owner through specialization. Field names have explicit source spans in the
AST; HIR method spans identify the name rather than the `fn` keyword. A missing
member does not fall back to an unrelated module-level declaration with the same
name. Declaration clicks and reference searches share the member's definition ID.

Member hover combines original declaration documentation and parameter names
with receiver-specialized types. Signature help resolves the callee by its
token position, not a workspace-wide name search, and excludes the implicit
`self` argument. Its cursor query reuses existing tokens. During incomplete
argument input the editor parser retains the call and receiver while reporting
the syntax error; strict parsing still rejects the incomplete call.

Dynamic-trait member queries follow transitive inheritance. Inherited methods
keep the signature identity of their declaring trait, and cache validation also
tracks the visible inheritance scope. Removing a base trait therefore removes
its methods without editing the caller. Functions without a `self` parameter
are not offered as instance members.

Generic function and impl bounds contribute a body-local method environment.
The same environment drives call-result inference and completion, including
parameterized trait bounds and `Self` results. Editing an impl's bounds
invalidates its cached body queries even when the method body text is unchanged.
Trait inheritance specializes the parent's arguments along each edge. Parameter
substitution is simultaneous, so reordered arguments do not overwrite one
another; `Self` remains tied to the final receiver through inherited methods.
Receiver specialization uses the generic parameters recorded in the declaration,
not capitalization or identifier length. Nested generic receiver patterns and
repeated parameters are matched structurally. Concrete impl arguments must match
the receiver, so an impl for `Box[u32]` does not supply methods to `Box[str]`.
The declaration's generic parameter list participates in cache validation.

Associated calls such as `Vec[T]::new()` are checked against declared static
methods. Their parameters and return types are specialized through the impl's
generic receiver, including `Self`; a static method may return a different type
from its owner. Static methods are not offered for `value.` and are not accepted
as instance calls. Static/instance identity participates in signature validation.
Editor queries preserve generic arguments before an associated member name.
Hover, signature help and reference highlights resolve that owner through the
module type namespace, including imported aliases, and reuse the declared
static method's specialized signature and documentation. An incomplete argument
list does not prevent signature help.
Completion after a type's `::` uses the same static-member query, including
an empty or partially typed member name. It preserves explicit generic
arguments and imported type aliases; instance fields and methods are excluded.
Associated editor queries retain the original owner spelling until it resolves
to a declaration. Method selection compares that declaration's physical identity
with the impl target resolved in its own module; two same-named types from
different files therefore do not share static methods. Fully qualified owners
can be discovered without adding an import, while public visibility still
applies. Import aliases used in impl targets are normalized before generic
specialization without changing the method's declaration location.
Member references use a source-based declaration identity, retaining the owner,
kind, name and ordinal. Logical module names and URI views of the same source
therefore do not create false ambiguous member declarations; different source
files or owners remain distinct.

Nominal HIR type IDs use their physical declaration rather than a short name.
A structural identity query resolves aliases inside nested type arguments while
keeping the supplied display text separate. Generic parameter identities include
their declaration scope; unresolved names remain unknown. Field descriptors
also retain their original declaring owner independently of the receiver spelling
used for lookup. Body inference now carries opaque nominal identities through
parameters, local annotations, function results, fields and methods. Public
binding/receiver queries and diagnostics render readable type names separately;
two imported aliases of different same-named declarations do not share instance
methods or inferred return types. Generic parameters remain local to their
declarations instead of resolving to a same-named nominal type.

The normalized member environment is cached per module and database revision,
not rebuilt for each hover or definition request. Signature normalization selects
the declaring module's type bindings once for each adjacent group of declarations,
instead of scanning every reachable module for every parameter. Type rendering
reuses strings without internal identities; its byte-indexed scanner uses byte
slices so Unicode text is not split with character offsets.
Cached bodies also track the
type namespaces of their own module and used signatures: redirecting an alias
must invalidate inference even when signature text and caller body are unchanged.
These namespace dependencies are conservative; unrelated body-only edits do
not invalidate them. Full structural type propagation, qualified type paths in
every expression context, and replacing legacy library-name-based operations
with declaration-driven language items remain migration work.

## Diagnostics

A diagnostic contains a stable code, severity, primary message, primary and
secondary labelled spans, notes, help, and zero or more source suggestions.
Suggestions carry an applicability classification so only
`machine-applicable` edits may be applied automatically.

Terminal, JSON, LSP, and IDE output are projections of this same structured
value. No consumer reconstructs labels or fixes by parsing human-readable
messages.

## Project configuration

Tooling configuration lives in `encore.toml`:

```toml
[lint]
default = "warn"
dependencies = "allow"
cap = "deny"

[lint.rules]
unused = "warn"
unused-imports = "deny"
unreachable-code = "deny"
missing-public-docstring = "deny"

[format]
line-width = 100
indent-width = 4
newline-style = "auto"
trailing-comma = "vertical"
reorder-imports = true
format-docstrings = true
```

Unknown keys, rule names, and values are errors. Command-line lint levels
override manifest defaults. LSP and direct IDE clients receive the normalized
configuration from the project layer rather than parsing TOML themselves.
`missing-module-docstring` and `missing-public-docstring` are `allow` by default.
Enable them explicitly in `[lint.rules]` for projects which require module or
public API documentation.
`dependencies = "allow"` skips dependency linting; any other level analyzes
loaded dependency modules at that uniform capped level. `newline-style =
"auto"` produces deterministic LF output; use `"crlf"` for an explicit CRLF
policy.

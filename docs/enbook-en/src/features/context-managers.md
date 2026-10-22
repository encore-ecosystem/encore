# Context Managers

`with value as name { ... }` calls the value's `ContextManager` entry and exit
operations on every control-flow path. Use it for resources whose cleanup
must run on normal exit, early return, or loop transfer.

Nested contexts exit from inner to outer, exactly once. Returning an error
with `?` exits the active contexts too. A `break` or `continue` exits only
contexts inside its target loop; a context surrounding that loop stays open.
This also applies to transfers targeting a labeled outer loop.

Return expressions are evaluated before cleanup. Managed values returned from
a context keep their ownership, but this does not extend the lifetime of an
external resource closed by `with_exit` (for example, a file or GPU scope).

```encore
{{#include ../../examples/guide/src/features/mod.enq:context}}
```

# Context Managers

`with value as name { ... }` calls the value's `ContextManager` entry and exit
operations on every control-flow path. Use it for resources whose cleanup
must run on normal exit, early return, or loop transfer.

```encore
{{#include ../../examples/guide/src/features/mod.enq:context}}
```


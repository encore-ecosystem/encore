# Attributes, `cfg`, and Tests

Compile-time metadata begins with `#`. `#cfg(...)` selects an item for a
target; `#attr(test)` registers a test, and other `#attr(...)` values guide
compiler lowering. These are not runtime calls.

```encore
{{#include ../../examples/guide/src/features/mod.enq:attributes}}
```

Common `cfg` predicates include `windows`, `unix`, `target_os = "..."`, plus
`all(...)`, `any(...)`, and `not(...)`.


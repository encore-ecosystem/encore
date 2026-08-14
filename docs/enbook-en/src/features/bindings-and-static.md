# Bindings, Mutability, and Static Values

`let` creates an immutable binding and `let mut` permits reassignment.
`static` defines a process-wide value initialized once. Prefer immutable
values and make mutability explicit at the narrowest useful scope.

```encore
{{#include ../../examples/guide/src/features/mod.enq:bindings}}
```


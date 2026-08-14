# Traits and Dynamic Dispatch

Traits define behavior contracts. Generic trait bounds use static dispatch;
`dyn Trait` explicitly creates a trait object for heterogeneous values and
dynamic dispatch.

```encore
{{#include ../../examples/guide/src/features/mod.enq:traits}}
```

Object-safety diagnostics reject trait methods that cannot be represented by
a dynamic vtable contract.


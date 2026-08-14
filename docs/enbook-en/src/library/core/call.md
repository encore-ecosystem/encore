# `core::call`

Defines the compiler-recognized `Fn`, `FnMut`, and `FnOnce` callable traits
and the `Callable[Args, Output]` surface used by decorator wrappers. Prefer a
generic callable when static specialization is possible.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:call}}
```


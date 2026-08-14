# `std::future`

Re-exports the core future protocol and adds `block_on`, the synchronous
executor boundary for a concrete `Future[T]`.

```encore
{{#include ../../../examples/guide/src/features/mod.enq:async}}
```


# `core::result`

`Result[T, E]` holds `Ok(T)` or `Err(E)`. Methods and free functions expose
status checks and fallbacks; `?` provides typed early propagation.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:result}}
```


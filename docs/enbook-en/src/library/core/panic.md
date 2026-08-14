# `core::panic`

`panic(message)` aborts the current program for an unrecoverable invariant
failure. Use `Result` for failures callers can reasonably handle.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:panic}}
```


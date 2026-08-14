# Spawn and Join

`spawn function(args)` starts a direct Encore function call on a worker thread
and returns `JoinHandle[T]`. Calling `join()` consumes the handle and returns
the worker result.

```encore
{{#include ../../examples/guide/src/features/mod.enq:spawn}}
```

The compiler checks that values crossing the thread boundary satisfy the
ownership and pointer-safety rules.


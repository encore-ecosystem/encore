# `std::thread`

Re-exports `JoinHandle[T]` and `available_parallelism`. Create handles with the
language-level `spawn` expression and consume them with `join()`.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:thread}}
```


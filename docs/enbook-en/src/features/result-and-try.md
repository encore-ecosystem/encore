# `Result` and `?`

`Result[T, E]` makes recoverable failure part of a function's type. Matching
handles both cases explicitly; postfix `?` returns an `Err` immediately and
unwraps `Ok` for the rest of the expression.

```encore
{{#include ../../examples/guide/src/features/mod.enq:result}}
```


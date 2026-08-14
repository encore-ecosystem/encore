# `core::option`

`Option[T]` represents `Some(T)` or `None` without a sentinel value. Its
methods include `is_some`, `is_none`, `unwrap_or`, Boolean combinators, and
`flatten`.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:option}}
```


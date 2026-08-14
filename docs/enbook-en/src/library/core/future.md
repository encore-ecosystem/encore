# `core::future`

Contains `Future[T]`, `Poll`, `Context`, `Waker`, and the immediately-ready
`Ready[T]` future. Executors poll through this minimal protocol.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:future}}
```


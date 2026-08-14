# Async and Await

`async fn` returns a concrete state-machine type implementing `Future[T]`.
`await` suspends that state machine without blocking its executor thread.
`std::future::block_on` drives a future to completion at a synchronous edge.

```encore
{{#include ../../examples/guide/src/features/mod.enq:async}}
```


# `core::iter`

Defines `Iterator`, `IntoIterator`, `Enumerate`, and range iterators used by
`for`. The iterator state is explicit and can be specialized.

## User-defined iterators

Implement `Iterator[Item]` with
`next(self: Self) -> (Self, Option[Item])`. The first result is the next
iterator state; the second is the item, or `None` to finish the loop.
An iterator itself can be used directly in `for`.

A collection can instead implement `IntoIterator[Item, Iter]` with
`into_iter(self: Self) -> Iter`, where `Iter` implements `Iterator[Item]`.
The compiler calls `into_iter` once, then `next` before each iteration.
An inherent method named `next` alone does not make a type iterable.

Generic collections and generic functions with iterator bounds use the same
protocol. Owning items follow the usual lifetime rules: `break`, `continue`,
and an early return release the iterator and items no longer needed, while
a returned item remains alive.

```encore
{{#include ../../../examples/guide/src/core_examples/mod.enq:iter}}
```

# Methods and Receivers

`impl for Type` adds inherent methods. The `self` parameter states receiver
ownership and `self: mut Self` authorizes mutation. Methods can return `Self` for
builder-style APIs.

```encore
{{#include ../../examples/guide/src/features/mod.enq:methods}}
```

`current` reads; `increment` requests a mutable receiver. The caller must
provide a mutable path. A method that returns `Self` may instead implement a
value-transforming builder: keep its returned value rather than assuming
that a discarded result updated the original.

For node payload mutation, use an appropriate node receiver such as
`self: mut Self&`. `&` does not itself mean mutable. Choose inline versus node
representation first, then the receiver capability. See
[values and sharing](../values-and-sharing.md).

**Exercise:** a `len` method only reads collection state. Should it request
`mut`? No: doing so needlessly prevents calls from read-only paths.

An associated function declared without a `self` parameter is also callable
through an instance: `value.create()` resolves to the same declaration as
`Type::create()`, without passing an implicit receiver argument. The instance
expression is still evaluated once. This uses the receiver type and its
visible impls, regardless of the variable's name. Within an impl, `self::create()`
is an alias for `Self::create()`.

Visibility is independent of receiver binding. An inherent method without
`pub` is private to its declaring type. Only an `impl` of that same nominal
type may call it, including through another instance or `Self::method()`.
Free functions and other types need a public method even in the same module.
Aliases and same-spelled unrelated types do not change this boundary.
Implicit calls made by operators, iteration and `with` obey the same boundary.
Trait implementation methods remain accessible through their trait contract.
Dynamic trait receivers expose receiver methods, rather than associated functions.

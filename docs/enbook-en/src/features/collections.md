# Tuples, Arrays, and Vectors

Tuples combine heterogeneous values, arrays have fixed length, and `Vec[T]`
is a growable homogeneous collection. Indexing an array returns its element;
`Vec.get` returns `Option[T]` so bounds failure is explicit.

```encore
{{#include ../../examples/guide/src/features/mod.enq:collections}}
```


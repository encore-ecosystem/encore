# `std::dict`

Provides `Hashable` and `Dict[K, V]`. Keys implement hashing and equality;
updates return the next dictionary value and lookup returns `Option[V]`.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:dict}}
```


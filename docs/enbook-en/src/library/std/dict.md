# `std::dict`

Provides `Hashable` and `Dict[K, V]`. Keys implement hashing and equality;
`insert` and `remove` mutate the dictionary and return the previous `Option[V]`.
Lookup also returns `Option[V]`. There is no separate `dict` dependency: add
`std` and import `std::dict::{Dict, Hashable}`.

For 0.1.1, storage remains a vector of pairs with linear search: lookup,
insertion and removal are O(n). Hash-table optimization is deferred.
The `Hashable + Eq` bounds remain, but lookup currently uses equality only.

Copies share storage. `clone()` makes an independent collection (not a deep clone
of values). `keys()`, `values()` and `items()` allocate snapshots.
`reserve(additional)` reserves room for more entries; `clear()` removes all
entries. Do not assume constant-time lookup for large collections.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:dict}}
```

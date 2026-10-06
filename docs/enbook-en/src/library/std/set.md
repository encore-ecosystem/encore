# `std::set`

`Set[T]` stores unique values with `Hashable + Eq` bounds, using `Dict`.
`insert` returns whether a value was new; `remove` returns whether it existed.
Both mutate the set. `contains`, `len` and `is_empty` inspect it.

`union`, `intersection` and `difference` return new independent sets;
`is_subset` checks containment. Copies share storage; `clone()` copies the
table. `values()` returns a snapshot vector. Iteration order is unspecified.
The dictionary currently uses linear search, so membership is O(n) and set
algebra can be quadratic. Hash-table optimization is deferred beyond 0.1.1.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:set}}
```

# Operators and Casts

Arithmetic, comparison, bitwise, shift, and compound-assignment operators are
resolved through `core::ops`. `as` performs an explicit supported conversion;
it does not silently reinterpret an unrelated representation.

A `*` after an `as` target can belong to a raw pointer type. Parenthesize a
scalar cast before multiplying, for example `(cycles as f32) * duration`.
Assigning a raw pointer to a numeric value is a source type error.

```encore
{{#include ../../examples/guide/src/features/mod.enq:operators}}
```

`**` is exponentiation and is right-associative. Boolean `&&` and `||`
short-circuit.

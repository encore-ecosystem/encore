# Operators and Casts

Arithmetic, comparison, bitwise, shift, and compound-assignment operators are
resolved through `core::ops`. `as` performs an explicit supported conversion;
it does not silently reinterpret an unrelated representation.

```encore
{{#include ../../examples/guide/src/features/mod.enq:operators}}
```

`**` is exponentiation and is right-associative. Boolean `&&` and `||`
short-circuit.


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

Arithmetic, bitwise and shift traits take two mandatory type arguments:
`Trait[Rhs, Output]`. The right operand and the result may have different types
from the left operand:

```encore
import core::ops::Add

struct Distance { meters: u32 }

impl Add[u32, Distance] for Distance {
    fn op(self: Self, other: u32) -> Distance {
        ret Distance { self.meters + other }
    }
}

impl Add[Distance, u64] for Distance {
    fn op(self: Self, other: Self) -> u64 {
        ret (self.meters as u64) + (other.meters as u64)
    }
}
```

This applies to `Add`, `Sub`, `Mul`, `Div`, `Rem`, `Pow`, `BitAnd`, `BitOr`,
`BitXor`, `Shl` and `Shr`. Comparison traits such as `Eq[Rhs]` still return
`bool` and take one type argument. Generic bounds use the same contract, for
example `L: Add[R, O]` for a function returning `O` from `lhs + rhs`.

Operators require an implementation for the actual operand types. A `u8`
variable and a `u16` variable cannot be added by implicit widening; convert
explicitly with `as` or `From`/`Into`. Unsuffixed numeric literals can use the
operand type required by the selected implementation. A pair of operand types
must have one result type per operator; changing the expected result type does
not select between competing implementations.

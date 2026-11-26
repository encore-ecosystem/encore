# Functions and Generics

Functions declare parameter and result types. Generic parameters are written
in brackets and are monomorphized for concrete uses, so abstraction does not
require dynamic dispatch unless the program asks for `dyn Trait`.

```encore
{{#include ../../examples/guide/src/features/mod.enq:functions}}
```

## Let the call provide context

`identity(42_u32)` specializes `T` as `u32`; `identity[u32](42)` supplies the
type explicitly. Specify types when empty containers or ambiguous calls give
the compiler too little information. Generic parameters describe types, not
dynamic values to inspect at runtime.

A function using a trait-defined operation must declare the required bound
and have the trait visible. An unconstrained `T` is not a promise that every
operation will work for every caller. A missing bound should be fixed in the
contract, not deferred until a particular use accidentally happens to compile.

## Default parameters and named arguments

A trailing parameter may have an integer, floating-point, boolean, or string
literal as its default. Signed numeric literals and numeric type suffixes are
accepted. The literal must fit the declared scalar type; calls and other
expressions are not defaults.

```encore
fn weighted(x: u32, y: u32 = 2, z: u32 = 3) -> u32 {
    ret x * 100_u32 + y * 10_u32 + z
}

// 123, 129, and 128 respectively:
weighted(1)
weighted(z: 9, x: 1)
weighted(1, z: 8)
```

Required parameters precede parameters with defaults. Positional arguments
precede named arguments. Each parameter can be supplied once, and every required
parameter must be supplied. Explicit arguments are evaluated once, from left to
right as written, even when names put them in a different parameter order.

The same rules apply to methods, generic functions, async functions, and
generators. A trait owns its public parameter names and defaults: put defaults
on the trait declaration and omit them from implementations. An implementation
may use different local parameter names. Calls use the names from the trait.

Defaults belong to the declaration and are inserted by the caller. The binary
function signature still contains every parameter. Changing a public parameter
name or default changes the package interface and invalidates cached callers.
An indirect function value carries its function type rather than declaration
defaults or parameter names; supply its arguments positionally and in full.

Use concrete parameter types for concrete APIs. Generic code is useful when
several types genuinely share an algorithm. For runtime-selected heterogeneous
implementations, see [traits](traits-and-dyn.md).

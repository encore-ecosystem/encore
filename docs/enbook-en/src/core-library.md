# Core Library

`core` is the compiler's minimal language-support library. It defines
callables, casts, formatting, futures, iteration, operator traits,
`Option`, `Result`, panic/testing primitives, and `Vec` without depending on
the hosted platform layer.

Every public core module has a dedicated page below with a compile-checked
example. Applications normally receive `core` from the installed target kit.

`core::convert::{From, Into}` defines infallible conversions. Implement
`From[Source]` for the destination type with a static
`fn from(value: Source) -> Self` method. The blanket `Into[Target]`
implementation then makes `value.into()` available when `Target: From[Source]`.
`std::convert` re-exports the same traits.

The destination can come from a binding annotation, a return type, a function
parameter, or an explicit `Into[Target]::into(value)` call. A conversion without
enough destination context is rejected. Generic conversion functions declare
the complete `Source: Into[Target]` or `Target: From[Source]` bound.

Primitive `From` implementations cover identity and lossless numeric widening.
Narrowing conversions require an explicit cast. When a `Result` expression uses
`?`, its error can be converted to the enclosing result's error through `From`.


# Strings and F-Strings

`str` is the built-in string value. Prefix a literal with `f` to interpolate
expressions directly. `{name}` uses a visible binding and `{expression}`
evaluates an expression once at the interpolation point.

```encore
{{#include ../../examples/guide/src/features/mod.enq:strings}}
```

Escape a literal brace as required by the formatter grammar; use
`std::string::String` when an owned, method-rich string wrapper is useful.


# `std::num`

`parse[T](text)` parses a decimal integer. `parse_radix[T](text, radix)`
accepts bases 2–36; radix zero recognizes `0x`, `0o`, `0b` (either case),
and otherwise uses decimal. Explicit bases accept digits without prefixes.
Import `Integer` alongside the parsing functions for generic trait lookup.

All signed and unsigned integer types are supported. A leading `+` is
accepted; negative unsigned values are rejected. Whitespace, underscores and
non-ASCII digits are rejected. Parsing never silently wraps: errors are
`Empty`, `InvalidRadix`, `InvalidDigit` or `Overflow` in `ParseIntError`.
Floating-point parsing is not part of this module.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:num}}
```

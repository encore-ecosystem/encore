# The `format!` Macro

`format!` creates a `str` without writing to a stream. Positional `{}` slots
consume trailing arguments, while named slots read visible bindings. Values
implementing `core::fmt::Debug` can participate in formatting.

```encore
{{#include ../../examples/guide/src/features/mod.enq:formatting}}
```


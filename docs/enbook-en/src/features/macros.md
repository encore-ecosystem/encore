# Declarative Macros

`macro_rules!` transforms syntax at compile time. Arms match token fragments
such as `expr` and `ident`, then substitute them into a template. Macro calls
end with `!`.

```encore
{{#include ../../examples/guide/src/features/mod.enq:macros}}
```


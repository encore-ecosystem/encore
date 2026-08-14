# Functions and Generics

Functions declare parameter and result types. Generic parameters are written
in brackets and are monomorphized for concrete uses, so abstraction does not
require dynamic dispatch unless the program asks for `dyn Trait`.

```encore
{{#include ../../examples/guide/src/features/mod.enq:functions}}
```


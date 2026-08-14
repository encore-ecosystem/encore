# Methods and Receivers

`impl for Type` adds inherent methods. The `self` parameter states receiver
ownership and `mut self` authorizes mutation. Methods can return `Self` for
builder-style APIs.

```encore
{{#include ../../examples/guide/src/features/mod.enq:methods}}
```


# Closures

Closures use `|arguments| expression` or `|arguments| { ... }`. Captured
values become closure environment fields. A closure can satisfy a compatible
trait object when its call shape matches the trait's method.

```encore
{{#include ../../examples/guide/src/features/mod.enq:closures}}
```

The compiler rejects a closure whose captured stack references escape their
valid lifetime.


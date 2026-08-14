# Enums and Pattern Matching

Enum variants may be unit-like or carry fields. `match` destructures the
selected variant, and semantic checking requires exhaustive, non-duplicated
coverage.

```encore
{{#include ../../examples/guide/src/features/mod.enq:enums}}
```


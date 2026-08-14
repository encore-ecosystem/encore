# `std::fs`

Provides filesystem existence, text reads and writes, removal, directory
creation, and directory listing. Operations that can fail expose native status
or a documented fallback; use `std::path::Path` for composition.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:fs}}
```


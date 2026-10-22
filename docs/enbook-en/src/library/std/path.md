# `std::path`

`Path` parses and normalizes platform-aware paths and supports joining,
absolute resolution, home expansion, parents, names, and filesystem helpers.

Use `/` to append a string component. Chaining is supported, and an absolute
right-hand path replaces the base, following the same rules as `join`.

```encore
import std::path::Path

let config = Path::cwd() / "root" / "settings.env"
```

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:path}}
```

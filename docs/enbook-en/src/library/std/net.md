# `network`: TCP

Add `sys@network` to dependencies. `Stream`, `Listener`, `ConnectOptions` and
`ListenOptions` provide TCP and context-manager cleanup. Networking is separate
from `std`; the former `std::net` API has been removed.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:net}}
```


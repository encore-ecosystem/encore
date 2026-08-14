# `std::http`

Provides URL parsing, request and response values, configurable clients, TLS
transport, redirects, and bounded response parsing.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:http}}
```

Network operations return `Result[..., str]`; configure body and timeout
limits before accepting untrusted endpoints.


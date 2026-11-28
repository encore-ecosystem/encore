# `network`: TLS

Use `ConnectOptions::tls` and `Stream::connect`, or their async counterparts.
TLS uses network's OpenSSL backend, with custom CA files supported. The former
`std::tls` API has been removed.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:tls}}
```


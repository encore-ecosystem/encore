# `std::http`

Provides URL parsing, shared request and response values, blocking and
nonblocking clients, TLS verification, and bounded response parsing.

`HTTPSyncClient::new().get(url)` returns `Result[HttpResponse, HTTPError]`.
`HTTPAsyncClient::new()` returns a result containing a client that owns its
reactor. Its `get` and `send` methods return `HTTPResponseFuture` for `await` or
`std::future::block_on`; no HTTP-specific executor is needed. Use a with-context
or explicitly close the async client. Copies share the reactor and close state.

Both clients accept `HttpClientConfig` and `HttpRequest`, return `HttpResponse`,
and report typed `HTTPError` values. Requests do not follow redirects or retry
automatically. The compatibility `HttpClient` retains its redirecting `get` and
string errors.

The async backend initially supports Linux with OpenSSL and c-ares >=1.34
development packages. Other targets report an unsupported configuration when
creating an async client. The sync client retains the platform TLS fallback.
Plain HTTP is restricted to loopback addresses.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:http}}
```

Configure body, header and timeout limits through `HttpClientConfig`.

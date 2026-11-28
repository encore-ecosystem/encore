# `http`

Provides URL parsing, shared request and response values, blocking and
nonblocking clients, TLS verification, and bounded response parsing.

`HTTPSyncClient::new().get(url)` returns `Result[HttpResponse, HTTPError]`.
`HTTPAsyncClient::new()` returns a result containing a client with its own request group on the shared network
reactor. Its `get` and `send` methods return `HTTPResponseFuture` for `await` or
`std::future::block_on`; no HTTP-specific executor is needed. Use a with-context
or explicitly close the async client. Copies share the client close state; other clients remain independent.

Both clients accept `HttpClientConfig` and `HttpRequest`, return `HttpResponse`,
and report typed `HTTPError` values. Requests do not follow redirects or retry
automatically. The compatibility `HttpClient` retains its redirecting `get` and
string errors.

Add `sys@http` to dependencies. Sync and async clients run on Linux, macOS and
Windows through `network` and its OpenSSL backend. TLS uses OpenSSL trust
configuration, with `with_ca_file` for a custom CA.
Plain HTTP is restricted to loopback addresses.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:http}}
```

Configure body, header and timeout limits through `HttpClientConfig`.

Async requests are lazy: their first poll submits them to the reactor. An
unfinished `HTTPResponseFuture` returned by a select or timeout retains its
waker registration and can be resumed by another `block_on` call on the same
owning thread. Dropping the final future owner abandons its native request.
Dropping the final client owner stops and joins the reactor before freeing it;
`close()` remains available for explicit, shared shutdown.

Use `.with_token(std::sync::CancellationToken)` for cancellation shared with
other SDK operations. The existing `.with_cancellation(HTTPCancellationToken)`
API remains client-specific and rejects a token from another reactor. Neither
API makes a client or request transferable across threads.

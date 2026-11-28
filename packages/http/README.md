# HTTP for Encore

Add `sys@http` to the project dependencies and import `http::{HttpClient,
HTTPSyncClient, HTTPAsyncClient, HttpClientConfig, HttpRequest, HttpResponse, Url}`.
HTTP/1.0 and HTTP/1.1 clients share the `network` TCP/TLS reactor on Linux,
macOS and Windows. Basic std programs do not include this package.

`HttpClient::get` preserves redirects; `send` never redirects or retries.
`HTTPSyncClient` blocks on the same request future used by `HTTPAsyncClient`.
Use `with client as client` or `close()` to cancel a client's requests.
Requests are lazy, bounded by header/body limits and one overall deadline.
Unfinished futures retain owned operation registrations across executor handoff;
final drop cancels their I/O and closes their connection. Closing a client does
not stop the shared network reactor or another client.

URLs accept HTTPS and loopback HTTP. TLS validates certificates and hostnames
through network's OpenSSL backend; `with_ca_file` provides a custom CA file.
Default limits and public HTTP types match the former std HTTP API.
The old `std::http`, `std::net` and `std::tls` imports have been removed.

Run `encore check`, `encore lint`, `encore test` and, from the compiler root,
`python3 scripts/test-http-async.py --compiler target/extreme/encore`.

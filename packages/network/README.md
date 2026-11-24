# Network for Encore

Synchronous and asynchronous TCP/TLS streams and listeners for macOS and Linux.
Requires Encore 0.1.12, clang and OpenSSL 3. `build.enq` builds the native backend;
set `OPENSSL_DIR` for a custom OpenSSL prefix. Homebrew's `openssl@3` and the Linux
system installation are discovered automatically.

`Stream::connect(ConnectOptions::tcp(host, port))` opens TCP. Use
`ConnectOptions::tls` for verified TLS and optionally set `ca_file`.
`Listener::bind(ListenOptions::tls(host, port, cert, key))` serves TLS.
Streams expose `read(max)`, `write_all(bytes)`, and `close()`. Listeners expose
`accept()`, `local_port()`, and `close()`. Set `timeout_ms` on options and handles.
Every I/O method has an `_async` counterpart returning a named Encore future.
Binary data is a raw Encore byte string; `byte(u8)` constructs arbitrary bytes.

One shared reactor handles TCP, TLS, Unix sockets and timers. It uses epoll on Linux and kqueue on macOS. Four DNS workers resolve names.
TLS requires version 1.2 or newer, verifies hostname/IP and CA trust, and sends
SNI for DNS names. Operations use opaque IDs; native workers retain no Encore
heap pointers. The backend follows Encore's std/platform networking and reactor
patterns and extends them with asynchronous accept, timers and byte mailboxes.

There may be one pending reader per stream/listener and up to 64 queued FIFO
writes. The process limit is 1,024 outstanding operations. Cancellation and
timeouts are explicit errors. Closing a handle cancels its operations. Timed-out
or cancelled writes close the connection to prevent reuse after a partial write.
Abandoned futures are detached when their runtime waker is destroyed. Treat
futures as single-consumer values. Always close streams, listeners and mailboxes;
streams and listeners also support context managers.

`Mailbox` is a bounded FIFO of byte strings for communication between threads.
`finish()` drains queued data before reporting closure; `close()` cancels and
frees it. Overflow reports a capacity error. Scratch slots and atomic counters on
handles support protocol implementations without passing mutable Encore graphs
between threads. `crypto` supplies SHA-1 (WebSocket handshake only), SHA-256,
HMAC-SHA256, hex, base64 and constant-time byte comparison.

```sh
encore format --check
encore check
encore lint
encore test --jobs 1
python3 tests/run-native.py
```

The native tests create disposable certificates, then exercise TCP/TLS, hostname
verification, operation cancellation, accept/read deadlines, ordered writes,
mailbox overflow, abandoned wakers and resource cleanup under ASan/UBSan.
The suite runs locally and needs no external server or credentials.

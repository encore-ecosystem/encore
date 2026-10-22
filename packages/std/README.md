# std

`std` is Encore's application standard library. It re-exports the stable parts
of `core` and adds higher-level modules for strings, paths, filesystem access,
collections, math and random numbers.

Add it to a package with:

```toml
[project]
name = "my_app"
target = "auto"
dependencies = [
    "index@std@^0.0.5",
]
```

Applications resolve this package through the configured Encore registry.

## HTTP

The patched local Encore 0.1.6 build provides `std::http::HTTPSyncClient` and `HTTPAsyncClient`.
Both use `HttpRequest`, `HttpResponse`, `HttpClientConfig`, `HTTPError` and
`HTTPErrorKind`. `send` performs one request without redirects or retries.
The compatibility `HttpClient` API, including its redirecting `get`, remains.

`HTTPSyncClient::new().get(url)` blocks and returns a result.
`HTTPAsyncClient::new()` returns a result containing a client that owns one
reactor thread. Use a with-context or explicitly close the client. Its `get`
and `send` return lazy `HTTPResponseFuture` values for ordinary `await` or
`std::future::block_on`; there is no HTTP-specific executor function.

Closing a client stops and joins its reactor. Waker teardown cancels abandoned
requests across clients before the executor event is freed. A pending future
has one consumer and must not be polled concurrently or moved between executors.
Clients are thread-affine; copies share the same close state.

The initial async backend supports Linux with OpenSSL and c-ares >=1.34
development packages. Other targets return a configuration error on async
client creation; the sync client uses the existing platform TLS transport.
HTTP/1.1 framing, binary bodies, DNS, TLS verification, cancellation, timeouts
and bounded request capacity are supported. Plain HTTP is restricted to loopback.

## Imports

Import one item:

```enq
import std::io::println
import std::string::String
```

Import several items from a package:

```enq
import std::{
    vec::Vec,
    option::Option,
    fmt::Debug,
}
```

Trait bounds are checked from imported traits. For `Dict`, import both the type
and `Hashable`:

```enq
import std::dict::{Dict, Hashable}
```

## Collections

### `std::vec`

`std::vec` re-exports `core::vec`.

Main types:

- `Vec[T]`
- `VecIter[T]`

Main methods:

- `Vec[T]::new()`
- `Vec[T]::with_capacity(cap)`
- `Vec[T]::singleton(value)`
- `len()`, `capacity()`, `is_empty()`
- `reserve(additional)`, `push(value)`, `set(index, value)`
- `get(index) -> Option[T]`, `first()`, `last()`
- `clear()`, `pop() -> (Vec[T], Option[T])`, `extend(other)`
- `iter()`, `into_iter()`

```enq
import std::option::Option
import std::vec::Vec

fn sum(values: Vec[u32]) -> u32 {
    let mut total = 0_u32
    for value in values {
        total = total + value
    }
    ret total
}

fn first_or_zero(values: Vec[u32]) -> u32 {
    match values.first() {
        Option[u32]::Some(value) => value
        Option[u32]::None => 0_u32
    }
}
```

### `std::dict`

`Dict[K, V]` is a small hash dictionary for beta workloads. Keys must implement
both `Hashable` and `Eq`. `std` provides `Hashable` for `str`, `bool` and the
integer types.

Main API:

- `Dict[K, V]::new()`
- `Dict[K, V]::with_capacity(capacity)`
- `len()`, `capacity()`, `is_empty()`
- `clear()`
- `insert(key, value) -> Dict[K, V]`
- `get(key) -> Option[V]`
- `contains_key(key) -> bool`
- `remove(key) -> (Dict[K, V], Option[V])`

```enq
import std::dict::{Dict, Hashable}
import std::option::Option

fn main() -> u32 {
    let mut scores = Dict[str, u32]::new()
    scores = scores.insert("alpha", 10_u32)

    match scores.get("alpha") {
        Option[u32]::Some(value) => ret value
        Option[u32]::None => ret 0_u32
    }
}
```

## Text

### `std::string`

`String` wraps `str` and provides value-style helpers.

Main API:

- `String::new()`
- `String::from_str(value)`
- `as_str() -> str`
- `len() -> usize` for character count
- `byte_len() -> usize`
- `is_empty()`
- `byte_at(index) -> Option[u8]`
- `char_at(index) -> Option[str]`
- `concat(rhs)`, `push_str(rhs)`
- `slice(start, len)` by character index
- `slice_bytes(start, len)` by byte index
- `starts_with(prefix)`, `ends_with(suffix)`, `contains(needle)`
- `trim_start()`, `trim_end()`, `trim()`
- `split_char(ch) -> Vec[String]`
- `split_whitespace() -> Vec[String]`

```enq
import std::string::String

fn normalize(value: str) -> str {
    ret String::from_str(value).trim().as_str()
}
```

## Errors And Optional Values

`std::option` and `std::result` re-export `core`:

- `Option[T]::Some(value)` and `Option[T]::None`
- `Result[T, E]::Ok(value)` and `Result[T, E]::Err(error)`
- `is_some`, `is_none`, `is_ok`, `is_err`
- `unwrap_or`, `unwrap_err_or`

Use `match` for normal control flow:

```enq
import std::option::Option

fn fallback(value: Option[u32]) -> u32 {
    match value {
        Option[u32]::Some(inner) => inner
        Option[u32]::None => 0_u32
    }
}
```

## Files And Paths

### `std::path`

`Path` stores normalized path parts and delegates filesystem operations to
`std::os`.

Main API:

- `Path::new(raw)`, `Path::cwd()`, `Path::home()`
- `as_str()`
- `is_absolute()`, `is_relative()`
- `join(part)`, `join_path(path)`, `left / "child"` via `Div[str]`
- `expanduser()`, `normalize()`, `absolute()`, `resolve()`
- `name()`, `file_name()`, `stem()`, `suffix()`, `extension()`
- `parent()`
- `with_suffix(suffix)`, `with_name(name)`
- `exists()`, `mkdir()`, `remove_file()`, `read_text()`, `write_text(contents)`

```enq
import std::path::Path

fn config_path() -> str {
    ret (Path::home() / ".config" / "encore.toml").as_str()
}
```

### `std::fs`

`import std::fs::File` provides checked file operations: `open`, `create`,
`read`, `read_all`, `read_line`, `write_all`, `flush`, `close`, and `lines`.
Use `with file as stream` with `core::ops::ContextManager` for cleanup on early
exit. `File` is also available through `std::io`.

String-path filesystem helpers:

- `exists(path) -> bool`
- `read_to_string(path) -> String`
- `read_to_str(path) -> str`
- `read(path) -> Result[str, IoError]`
- `write(path, contents) -> Result[(), IoError]`
- `fs_write(path, contents) -> i32`
- `remove_file(path) -> i32`
- `create_dir(path) -> i32`
- `read_dir(path) -> Vec[str]`

Checked reads and writes report open, transfer and close failures. The legacy
`fs_write`, remove and create operations return native status codes; zero means
success.

## OS, Process And Time

### `std::os`

Re-exported from `core::os`:

- `argc() -> usize`
- `argv(index) -> Option[str]`
- `args() -> Vec[str]`
- `cwd() -> str`
- `home_dir() -> str`
- `os_name() -> str`
- `path_separator() -> str`
- `read_file`, `write_file`, `file_exists`, `remove_file`, `mkdir`, `read_dir`

### `std::process`

- `Command::new(program)`
- `arg(value)`, `cwd(path)`
- `output() -> Output`
- `Output::code()`, `success()`, `text()`
- `success_code() -> i32`
- `failure_code() -> i32`
- `exit(code) -> i32`
- `exit_success() -> i32`
- `exit_failure() -> i32`

`Command` passes arguments directly without invoking a shell. `output` is a
blocking operation and currently combines stdout and stderr in observation
order.

```enq
import std::process::Command

fn main() -> u32 {
    let output = Command::new("encore").arg("check").cwd(".").output()
    if output.success() { ret 0_u32 }
    ret 1_u32
}
```

### `std::time`

- `time_ms() -> u64`
- `time() -> u64`
- `perf_counter_ms() -> u64`
- `perf_counter() -> u64`
- `sleep_ms(ms) -> bool`

## IO And Formatting

### `std::io`

- `print(value)`
- `println(value)`
- `eprint(value)`
- `eprintln(value)`
- `print_debug(value)`
- `println_debug(value)`

### `std::fmt`

The `Debug` trait supports primitive values, `String`, `Option`, `Result` and
`Vec`.

```enq
import std::fmt::Debug
import std::io::println

fn show(count: usize) {
    println("count=" + Debug::fmt(count))
}
```

## Networking

`std::net` exposes the beta TCP API implemented by the target-selected
`platform` refrain:

- `socket_addr(host, port) -> str`
- `TcpStream::connect(addr) -> Result[TcpStream, str]`
- `TcpStream::read(max) -> Result[str, str]`
- `TcpStream::write(data) -> Result[i32, str]`
- `TcpStream::close() -> Result[bool, str]`
- `TcpListener::bind(addr) -> Result[TcpListener, str]`
- `TcpListener::accept() -> Result[TcpStream, str]`
- `TcpListener::close() -> Result[bool, str]`

`TcpStream` and `TcpListener` implement `ContextManager`, so they can be used
with `with` when the program should close them at block exit.

`std::tls` exposes the verified blocking TLS client implemented by the
target-selected `platform` refrain.
`std::http` provides the synchronous and asynchronous clients described above,
as well as the compatibility client on that stream:

- `Url::parse(value)` parses absolute HTTPS URLs and loopback HTTP URLs;
- `HttpRequest::get(url)` and `encode()` create HTTP/1.1 requests;
- `HttpClient::new().get(url)` follows HTTPS redirects and returns `HttpResponse`;
- `HttpClientConfig` configures a private CA file, redirect limit, response-body
  limit and per-operation timeout.

```enq
import core::result::Result
import std::http::HttpClient

fn fetch() -> str {
    match HttpClient::new().get("https://example.com/") {
        Result::Ok(response) => { ret response.body() }
        Result::Err(error) => { ret "request failed: " + error }
    }
    ret ""
}
```

The compatibility client is blocking and supports HTTP/1.0 and HTTP/1.1 responses,
`Content-Length`, connection-close framing, chunked transfer encoding and
absolute or root-relative HTTPS redirects. HTTP/2, connection pooling and
server-side TLS remain follow-up work.

## Math And Random

### `std::math`

- `sin(x: f32) -> f32`
- `cos(x: f32) -> f32`
- `tan(x: f32) -> f32`
- `min(lhs, rhs)`
- `max(lhs, rhs)`
- `clamp(value, low, high)`

### `std::random`

`Random` is deterministic and returns the next generator state with every
sample:

- `Random::new(seed)`
- `seed()`
- `next_u64() -> (Random, u64)`
- `next_range(upper) -> (Random, u64)`

```enq
import std::random::Random

fn roll(seed: u64) -> u64 {
    let pair = Random::new(seed).next_range(6_u64)
    ret pair.1 + 1_u64
}
```

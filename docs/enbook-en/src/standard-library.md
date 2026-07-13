# Standard Library

Use `std` for application code. It re-exports stable `core` APIs and adds
higher-level modules.

```enq
import std::dict::{Dict, Hashable}
import std::{
    fmt::Debug,
    io::println,
    option::Option,
    string::String,
    vec::Vec,
}
```

## `Option` And `Result`

`std::option`:

- `Option[T]::Some(value)`
- `Option[T]::None`
- `is_some`, `is_none`, `unwrap_or`, `and`, `or`, `xor`, `flatten`

`std::result`:

- `Result[T, E]::Ok(value)`
- `Result[T, E]::Err(error)`
- `is_ok`, `is_err`, `unwrap_or`, `unwrap_err_or`

Prefer `match` when both cases need distinct behavior.

## `Vec`

`Vec[T]` is the beta growable array.

```enq
let mut values = Vec[u32]::new()
values = values.push(3_u32)
values = values.push(5_u32)
```

Main methods:

- construct: `new`, `with_capacity`, `singleton`
- inspect: `len`, `capacity`, `is_empty`
- update: `reserve`, `push`, `set`, `clear`, `extend`
- access: `get`, `first`, `last`, `pop`
- iterate: `iter`, `into_iter`

`get`, `first`, `last` and `pop` return `Option` because indexes can be absent.

## `Dict`

`Dict[K, V]` is a hash dictionary. Keys need `Hashable + Eq`. `std` implements
`Hashable` for `str`, `bool` and integer types.

```enq
import std::dict::{Dict, Hashable}
import std::option::Option

fn lookup() -> u32 {
    let mut dict = Dict[str, u32]::new()
    dict = dict.insert("answer", 42_u32)

    match dict.get("answer") {
        Option[u32]::Some(value) => value
        Option[u32]::None => 0_u32
    }
}
```

Main methods: `new`, `with_capacity`, `len`, `capacity`, `is_empty`, `clear`,
`insert`, `get`, `contains_key`, `remove`.

## `String`

`String` wraps `str` with helpers for common text work.

Main methods:

- construct: `new`, `from_str`
- inspect: `as_str`, `len`, `byte_len`, `is_empty`
- access: `byte_at`, `char_at`
- combine: `concat`, `push_str`
- slice: `slice`, `slice_bytes`
- search: `starts_with`, `ends_with`, `contains`
- trim/split: `trim_start`, `trim_end`, `trim`, `split_char`, `split_whitespace`

`len` counts characters. Use `byte_len` for bytes.

## `Path` And `fs`

`Path` stores normalized path parts:

```enq
import std::path::Path

fn output_path() -> str {
    ret (Path::cwd() / "target" / "out.txt").as_str()
}
```

Main `Path` methods:

- `new`, `cwd`, `home`, `as_str`
- `is_absolute`, `is_relative`
- `join`, `join_path`, `/`
- `expanduser`, `normalize`, `absolute`, `resolve`
- `name`, `file_name`, `stem`, `suffix`, `extension`, `parent`
- `with_suffix`, `with_name`
- `exists`, `mkdir`, `remove_file`, `read_text`, `write_text`

`std::fs` exposes string-path helpers: `exists`, `read_to_string`,
`read_to_str`, `write`, `remove_file`, `create_dir`, `read_dir`.

## IO, Formatting, OS, Process And Time

`std::io`: `print`, `println`, `eprint`, `eprintln`, `print_debug`,
`println_debug`.

`std::fmt`: `Debug::fmt(value)` for primitive values, `String`, `Option`,
`Result` and `Vec`.

`std::os`: `argc`, `argv`, `args`, `cwd`, `home_dir`, `os_name`,
`path_separator`, plus low-level file helpers.

`std::process`: `success_code`, `failure_code`, `exit`, `exit_success`,
`exit_failure`.

`std::time`: `time_ms`, `time`, `perf_counter_ms`, `perf_counter`, `sleep_ms`.

## Networking

`std::net` provides a synchronous TCP beta API:

- `socket_addr(host, port)`
- `TcpStream::connect`, `read`, `write`, `close`
- `TcpListener::bind`, `accept`, `close`

Network operations return `Result[..., str]` where the `Err` variant contains
the native error string.

## Math And Random

`std::math`: `sin`, `cos`, `tan`, `min`, `max`, `clamp`.

`std::random::Random` is deterministic:

```enq
let pair = Random::new(1_u64).next_range(10_u64)
let value = pair.1
```

Every random method returns the next `Random` state alongside the sampled value.

## `core`

`core` remains available for low-level APIs. Its package README documents the
full module list. Application packages should normally import from `std` unless
they specifically need `core::testing`, `core::panic`, `core::cast`, unsafe
runtime helpers, or direct `core` behavior.

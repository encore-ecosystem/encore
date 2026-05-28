# EHIR Runtime ABI (v0 draft)

This document defines the language/backend contract for runtime calls used by EHIR after lowering.

## Scope

EHIR core lowering may emit `extern fn __ehir_rt_*` calls.  
A backend that claims EHIR compatibility must provide these symbols with compatible signatures and semantics.

## Conventions

1. Function names are stable ABI symbols (no backend-specific renaming).
2. Primitive widths must match EHIR types exactly (`u8/u64/i32/usize/u1/...`).
3. `str` is an opaque runtime string handle owned by runtime conventions.
4. Return codes:
   - `0` means success for integer status APIs unless explicitly documented otherwise.
   - non-zero indicates failure.
5. Calls must be deterministic relative to runtime/environment inputs.

## Required symbol groups

### Time

- `__ehir_rt_clock_ms(kind: u8) -> u64`
- `__ehir_rt_sleep_ms(ms: u64) -> u1`

`kind` values:
- `0`: wall clock milliseconds
- `1`: monotonic/perf clock milliseconds

### IO

- `__ehir_rt_io_write(fd: i32, value: str) -> i32`

`fd` is backend/runtime-defined, but `1` and `2` should map to stdout/stderr where available.

### Process

- `__ehir_rt_proc_exit(code: i32) -> i32`

### String

- `__ehir_rt_str_len(value: str) -> usize`
- `__ehir_rt_str_byte_at(value: str, index: usize) -> u8`
- `__ehir_rt_str_concat(lhs: str, rhs: str) -> str`
- `__ehir_rt_str_slice(value: str, start: usize, slice_len: usize) -> str`

### Formatting

- `__ehir_rt_fmt_u64(value: u64) -> str`
- `__ehir_rt_fmt_i64(value: i64) -> str`
- `__ehir_rt_fmt_f64(value: f64) -> str`

### OS / FS

- `__ehir_rt_os_argc() -> usize`
- `__ehir_rt_os_argv(index: usize) -> str`
- `__ehir_rt_os_cwd() -> str`
- `__ehir_rt_fs_read_file(path: str) -> str`
- `__ehir_rt_fs_write_file(path: str, contents: str) -> i32`
- `__ehir_rt_fs_status(path: str) -> i32`
- `__ehir_rt_fs_remove_file(path: str) -> i32`
- `__ehir_rt_fs_mkdir(path: str) -> i32`
- `__ehir_rt_fs_read_dir(path: str) -> str`

### Network

- `__ehir_rt_net_tcp_connect(addr: str) -> i32`
- `__ehir_rt_net_tcp_bind(addr: str) -> i32`
- `__ehir_rt_net_tcp_accept(listener_fd: i32) -> i32`
- `__ehir_rt_net_tcp_read(fd: i32, max: usize) -> str`
- `__ehir_rt_net_tcp_write(fd: i32, data: str) -> i32`
- `__ehir_rt_net_tcp_close(fd: i32) -> i32`
- `__ehir_rt_net_last_error() -> str`

## Memory model boundary

`drop/cfree` graph semantics are language-level.  
Runtime ABI does not perform semantic ownership analysis; it only executes the primitive operations requested by lowered code.

## dyn Trait ABI (fat pointer + vtable)

Current EHIR lowering for `dyn Trait` uses a uniform trait-object ABI:

1. Runtime representation of `dyn Trait`:
   - `data_ptr: i8*`
   - `vtable_ptr: i8*`

2. `data_ptr` points to heap storage containing a concrete value payload.

3. `vtable_ptr` points to a trait-specific vtable object:
   - one slot per trait method,
   - each slot stores an erased function pointer (`i8*`).

4. Slot order is deterministic and backend-defined by trait method order contract used during lowering.

5. Dynamic dispatch:
   - lower `Trait::method(dyn_obj, ...)` to dyn-dispatch path,
   - read function pointer from method slot,
   - cast slot pointer to concrete call signature,
   - indirect-call with `self` reconstructed from `data_ptr`.

6. Null/uninitialized vtable slot is a hard runtime failure (`trap`), not silent fallback.

7. Object-safety remains a language-level check in EHIR (before backend codegen).

## Compatibility policy

Backend updates must preserve this ABI for the same major EHIR version.  
If a symbol or signature changes, it requires a coordinated ABI version bump and migration.

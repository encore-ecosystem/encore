# Native ABI Boundary

EHIR does not define or implement a language runtime.

Runtime-like functionality is supplied by frontends/packages through native
libraries. Encore's `core` package provides its native implementation via
`build.enq`, which asks the build system to compile and link `core/runtime.c`.

## Contract

1. EHIR may contain ordinary `extern fn` declarations.
2. Backends link the native libraries attached to the compiled refrain.
3. A backend is not required to implement any EHIR-owned runtime symbol family.
4. Package authors own the ABI names they expose through `extern fn`.

Encore reserves the `encore_*` C symbol prefix for its standard native ABI.
Those symbols are provided by Encore `core`, not by EHIR.

## Encore Core Native Symbols

The current Encore core native implementation exports symbols such as:

- `encore_clock_ms`
- `encore_sleep_ms`
- `encore_io_write`
- `encore_proc_exit`
- `encore_str_len`
- `encore_str_byte_at`
- `encore_str_concat`
- `encore_str_slice`
- `encore_str_char_len`
- `encore_str_char_at`
- `encore_str_slice_chars`
- `encore_fmt_u64`
- `encore_fmt_i64`
- `encore_fmt_f64`
- `encore_os_argc`
- `encore_os_argv`
- `encore_os_cwd`
- `encore_os_home_dir`
- `encore_fs_read_file`
- `encore_fs_write_file`
- `encore_fs_status`
- `encore_fs_remove_file`
- `encore_fs_mkdir`
- `encore_fs_read_dir`
- `encore_net_tcp_connect`
- `encore_net_tcp_bind`
- `encore_net_tcp_accept`
- `encore_net_tcp_read`
- `encore_net_tcp_write`
- `encore_net_tcp_close`
- `encore_net_last_error`
- `encore_gui_window_create`
- `encore_gui_window_is_open`
- `encore_gui_window_poll`
- `encore_gui_window_clear`
- `encore_gui_window_fill_rect`
- `encore_gui_window_present`
- `encore_gui_window_destroy`

This list documents Encore's current native package surface. It is not an EHIR
backend requirement.

## Memory Model Boundary

`drop/cfree/ERN` graph semantics are EHIR language semantics. Native libraries
do not perform ownership analysis; they only execute explicitly emitted calls.

## dyn Trait ABI

Current EHIR lowering for `dyn Trait` uses a uniform trait-object ABI:

1. Runtime representation of `dyn Trait`:
   - `data_ptr: i8*`
   - `vtable_ptr: i8*`
2. `data_ptr` points to heap storage containing a concrete value payload.
3. `vtable_ptr` points to a trait-specific vtable object.
4. Slot order is deterministic and follows trait method order after inherited
   methods are included.
5. Dynamic dispatch reads the function pointer from the vtable slot and performs
   an indirect call with `self` reconstructed from `data_ptr`.
6. Null/uninitialized vtable slots are hard failures (`trap`).
7. Object-safety is checked before backend codegen.

# `std::fs`

Provides filesystem existence, text reads and writes, removal, directory
creation, and directory listing. Use `std::path::Path` for composition.

`read(path)` returns `Result[str, IoError]`; `write(path, contents)` returns
`Result[(), IoError]`. Both check open, transfer and close failures. Whole-file
reads grow a buffer geometrically instead of repeatedly copying the full prefix.
For bounded memory use `File::read(size)` or the lazy `File::lines()` iterator.

Use `with file as stream` and import `core::ops::ContextManager` for cleanup
on early exit. Copies of a file share a cursor and close state. Explicit
`stream.close()?` lets callers observe close errors; context cleanup itself
does not turn a close failure into a returned `IoError`.

The legacy `read_to_str`/`read_to_string` return fallback values rather than
errors. `fs_write`, `remove_file`, `create_dir` and `create_dir_all` return
native status codes. They remain available for compatibility.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:fs}}
```

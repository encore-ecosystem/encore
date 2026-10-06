# `std::io`

Re-exports platform stream functions for standard input, output, and error,
including `print`, `println`, exact reads, and line reads.

`input(prompt) -> str` prints and flushes the prompt before reading. LF and
CRLF are removed, an empty line returns `""`, and an unterminated final line
is preserved. Pass `""` for no prompt. EOF and IO errors panic.
`try_input(prompt) -> Result[str, IoError]` is the recoverable alternative;
EOF has `IoErrorKind::UnexpectedEof`.

`File::open` and `File::create` return checked buffered streams. Methods:
`read(size)`, `read_all()`, `read_line()`, `lines()`, `write_all(data)`,
`flush()` and `close()`. `read_line()` returns `Ok(None)` at EOF and
`Ok(Some(""))` for an empty line. `lines()` yields `Result[str, IoError]`,
stopping after EOF or its first error. It does not close the file: use a
`with` context or explicit `close()`.

`IoError` contains `kind`, native `code` and human-readable `message`.
Closing any copy closes the shared file; subsequent reads return `Closed`.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:io}}
```

# ehir-interpret

Run typed EHIR directly with an instruction interpreter. Build the tool with
`encore build` in this directory and run `target/dev/ehir-interpret program.ehir`.
The program begins at `fn main() -> u32` and returns its process exit status.

```sh
encore build
./target/dev/ehir-interpret tests/fixtures/generator.ehir
```

The interpreter validates EHIR and uses the normal control-flow pass. It handles
integer and Boolean values, branches, loops, direct calls, explicit generic type
arguments, inline structs and enum payloads, and local stack places. Declare
`extern fn ehir_println_u64(value: u64) -> ()` to print an unsigned integer.

Generator calls create a lazy cursor. `Generator::next` resumes it and returns
the usual pair of cursor and `Option`. Retained copies share execution state.
Exhausted cursors keep returning `None`. Dropping the final reference to a
suspended cursor runs the cleanup calls attached to that `yield`.

The supported subset excludes async, arbitrary FFI, strings, floating-point
values, raw memory access and heap nodes. Execution is bounded by instruction
and call-depth limits. Instruction errors identify the source block and the
instruction within its normalized form.

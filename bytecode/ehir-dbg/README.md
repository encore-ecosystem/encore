# ehir-dbg

Build native LLVM objects with DWARF references to the original `.ehir` file.
The supported hosts are Apple Silicon macOS and x86-64 Linux. Build this package
with `encore build`, and use `CC` to select Clang if needed.

From the repository root, build a small EHIR program with debug information.

```sh
(cd bytecode/ehir-dbg && encore build)
mkdir -p target/ehir-debug
bytecode/ehir-dbg/target/dev/ehir-dbg \
  bytecode/ehir-interpret/tests/fixtures/values.ehir -o target/ehir-debug/values.o
clang -g target/ehir-debug/values.o -o target/ehir-debug/values
lldb target/ehir-debug/values
```

```text
(lldb) breakpoint set --file values.ehir --line 6
(lldb) run
(lldb) frame variable answer
```

Keep the object beside the executable on macOS, or run
`dsymutil target/ehir-debug/values` before moving the executable. Link the
program's native dependencies as usual. For example, a generator that uses
Encore's runtime also needs `packages/core/runtime.c` linked into the program.

The debugger emits source lines for ordinary functions and lowered coroutines.
Ordinary functions expose integer and Boolean parameters and SSA values.
Coroutine frame inspection is limited to source lines and the backtrace.

## Zed

Build and link the program first, then save this launch configuration in
`.zed/debug.json` at the workspace root. Open the `.ehir` source and start
**Debug EHIR** with `F4`.

```json
[
  {
    "label": "Debug EHIR",
    "adapter": "CodeLLDB",
    "request": "launch",
    "program": "$ZED_WORKTREE_ROOT/target/ehir-debug/values",
    "cwd": "$ZED_WORKTREE_ROOT"
  }
]
```

[Zed debugger configuration](https://zed.dev/docs/debugger#configuration)

# Encore Examples

Each directory is an independent Encore project. Build or run it with the
native compiler:

```sh
cd add_two_structs
encore build --profile release
encore run
```

Examples that accept arguments use the `--` separator:

```sh
cd echo
encore run -- hello Encore
```

The examples exercise language control flow, generics, collections, native
runtime APIs, networking, terminal output, EHIR and LLVM generation.

Native UI examples:

- `encore_ui_hello`: minimal retained window and layout;
- `encore_ui_counter`: state, buttons, widget IDs, and hit testing;
- `encore_ui_canvas`: immediate drawing for CAD and editor viewports;
- `encore_ui_demo`: composed toolbar and application workspace.

`bare_metal` is a freestanding Cortex-M project. It demonstrates a custom
startup source, memory layout, target flags, and linked firmware ELF without
requiring board-specific behavior in the compiler.

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

Concurrency examples:

- `async_pipeline` demonstrates lazy futures, wakeups, polling and `await`;
- `multithreading` divides CPU work between native threads with `spawn` and
  collects typed results with `JoinHandle::join`.

`bare_metal` is a freestanding Cortex-M project. It demonstrates a custom
startup source, memory layout, target flags, and linked firmware ELF without
requiring board-specific behavior in the compiler.

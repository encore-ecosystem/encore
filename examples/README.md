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

## Memory validation

Use Valgrind through the compiler to validate heap ownership and cfree behavior:

```sh
uv run encore-py memcheck --no-cache
```

The command builds the executable and runs it under `valgrind --leak-check=full`.
It exits with a non-zero status when Valgrind reports definite or possible leaks.

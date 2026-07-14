## Memory validation

Build with debug information and run Valgrind directly:

```sh
encore build --profile debug
valgrind --leak-check=full --error-exitcode=1 target/debug/heap
```

Valgrind exits with a non-zero status when it reports memory errors.

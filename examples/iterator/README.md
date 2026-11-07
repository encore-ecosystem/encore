# Generators

A function containing `yield` returns a lazy `core::iter::Generator[T]`.
The example yields five Fibonacci numbers and prints:

```text
1
2
3
5
8
```

Copies of a generator share its cursor. Separate calls create independent
sequences. The body runs only as the consumer requests values.

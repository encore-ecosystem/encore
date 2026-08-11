# Decorator Profile

This example profiles a function using a parameterized receiver-qualified
decorator. Encore expands the wrapper at compile time and emits a direct call
to the hidden function implementation.

```sh
encore run --profile release
```

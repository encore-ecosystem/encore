# `std::os`

Re-exports arguments, environment, host identity, filesystem primitives,
executable paths, checksums, and update helpers from the platform layer.

`env(name) -> Option[str]` reads the process environment. Missing or invalid names
return `None`; an explicitly empty value returns `Some("")`.

`set_env(name, value) -> Result[(), str]` sets a process environment variable,
replacing an existing value. Empty values remain present and child processes
inherit the updated environment. Empty names, names containing `=` or NUL, and
values containing NUL are rejected. Errors do not include the supplied value.
Set environment variables during startup, before tasks that access the environment.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:os}}
```

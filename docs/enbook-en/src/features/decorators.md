# Decorators

Mark a wrapper with `#attr(decorator)`, then apply it with `@expression`.
Encore specializes the wrapper around the original function during lowering;
it does not allocate a runtime reflection object or indirect callable.

```encore
{{#include ../../examples/guide/src/features/mod.enq:decorators}}
```

The required leading parameters are the original `Callable` and its packed
arguments. Extra decorator arguments follow them. Multiple decorators nest in
source order, and `@RENDER_PROFILE.profile("draw_frame")` works for methods as
well as free functions.


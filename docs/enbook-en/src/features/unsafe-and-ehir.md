# Unsafe Code and Embedded EHIR

`unsafe` marks operations whose invariants cannot be proven by ordinary
Encore checking, including native extern calls. Keep unsafe blocks small and
document the caller-visible invariant.

```encore
{{#include ../../examples/guide/src/features/mod.enq:unsafe}}
```

`ehir { ... }` and `unsafe ehir { ... }` embed EHIR instructions for compiler
and systems work. EHIR is an independent compiler IR and abstract machine;
Encore is one high-level frontend that lowers into it.


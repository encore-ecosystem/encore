# Structs and Node Placement

A plain struct value is inline and can be placed in a stack frame or enclosing
node. `T<H>` explicitly creates a heap node and returns an EHIR reference to
it. Placement is source-visible; it is not chosen later by a hidden GC.

```encore
{{#include ../../examples/guide/src/features/mod.enq:structs}}
```

See [Memory Model](../memory-model.md) for exclusively reachable nodes and
cascading deallocation.


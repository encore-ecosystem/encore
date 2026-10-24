# Bindings, Mutability, and Static Values

`let` creates an immutable binding and `let mut` permits reassignment.
`static` defines a process-wide value initialized once. Prefer immutable
values and make mutability explicit at the narrowest useful scope.

A static is initialized on its first read. Concurrent readers wait for the same
initializer; user initialization code runs outside the registry lock and may
read other statics. Recursive initialization and initialization cycles between
threads terminate with a diagnostic.

Each read returns an owning copy of the stored value. Reading a heap-node
static preserves the node's identity, so all readers observe the same node.
The stored root lives until process exit. A static cannot store a stack node or
a mutable local place. An omitted type is supported for literals and constructor
initializers; constructor inference preserves the resolved node placement.

```encore
{{#include ../../examples/guide/src/features/mod.enq:bindings}}
```

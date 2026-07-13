# Memory Model

Encore uses a graph-based memory model built on top of EHIR, the Encore High
Intermediate Representation. The goal is to give users the ergonomics of
reference-based languages while keeping deterministic cleanup and avoiding a
tracing garbage collector.

The short version is:

- primitive values are copied directly;
- every aggregate value is a reference to one heap resource node;
- the compiler retains references when they are shared;
- the compiler drops references when they leave scope;
- when the last reference to a node disappears, EHIR performs cascading
  deallocation for the part of the object graph that is no longer reachable.

Users normally do not write `Box` explicitly. The compiler uses it internally to
represent aggregate values as graph nodes.

## Two Kinds Of Types

Encore separates types into `ValueType` and `ReferenceType`.

### ValueType

Value types are copied directly and do not own graph resources.

Current value types are the primitive types:

- `bool`
- integer types such as `u8`, `u32`, `i32`, `usize`
- floating-point types such as `f32`, `f64`
- unit `()`

Assigning, passing or returning a primitive copies the bits:

```enq
let a = 10_u32
let b = a
```

After this code, `a` and `b` are independent `u32` values.

### ReferenceType

Reference types are aggregate values. They are represented as references to heap
nodes.

Reference types include:

- structs;
- enums;
- tuples;
- `str`;
- `Vec[T]`;
- dictionaries and other containers;
- file, socket, window and other resource handles;
- user-defined aggregate types.

For example:

```enq
struct Path {
    root: str
    parts: Vec[str]
}
```

`Path`, `str` and `Vec[str]` are all reference types.

## Hidden Box Representation

Every reference type is lowered as if it were stored inside a smart pointer:

```text
Path    -> Box[PathObject]
str     -> Box[StrObject]
Vec[T]  -> Box[VecObject[T]]
```

This `Box` is normally hidden from the user. It exists so EHIR can represent
memory as a graph:

```text
Path node
  root  -> Str node
  parts -> Vec node
             [0] -> Str node
             [1] -> Str node
```

The box/node stores the data needed by the memory model, including reference
counting metadata and the edges to other nodes.

From the user's point of view, the code still uses ordinary types:

```enq
let path = Path::new("src")
println(path.as_str())
```

The hidden representation is a compiler and EHIR detail.

## Sharing Is Retain

Reference values have reference semantics. When a reference value is assigned,
passed, returned or read from a field, the compiler retains the underlying node.

Assignment retains:

```enq
let a = Path::new("src")
let b = a
```

After this code, `a` and `b` refer to the same `Path` node. The node has two
live references.

Function calls retain arguments:

```enq
fn print_path(path: Path) -> () {
    println(path.as_str())
}

let p = Path::new("src")
print_path(p)
```

The call receives a retained reference. When `print_path` returns, its local
reference is dropped. The caller's `p` remains valid.

Field access retains reference fields:

```enq
let root = path.root
```

`root` is another reference to the same string node stored in `path.root`.

Loop variables retain elements:

```enq
for part in path.parts {
    println(part)
}
```

Each `part` is retained for the duration of the iteration and dropped at the end
of that iteration.

## Mutation Uses Shared Objects

Because aggregates are reference types, mutation changes the referenced object.

```enq
let mut values = Vec[u32]::new()
values.push(1_u32)
values.push(2_u32)
```

`Vec.push` mutates the vector node. It does not need to return a new vector for
ordinary mutation.

Sharing is visible:

```enq
let mut a = Vec[u32]::new()
let b = a
b.push(1_u32)

// a and b refer to the same vector node.
// a.len() is now 1.
```

This is intentional. Encore aggregate assignment behaves like sharing a Python
object or an ARC-managed object, not like copying a Rust `Vec`.

If code needs an independent aggregate, it must use an explicit clone-like API:

```enq
let b = a.clone()
```

The exact cloning API is library-defined.

## Dropping References

When a reference leaves scope, the compiler emits a drop operation for that
reference. Dropping a reference decreases the node's reference count.

```enq
fn make_path() -> Path {
    let path = Path::new("src")
    ret path
}
```

The returned value is transferred to the caller as a live reference. Local
references that are not returned are dropped before the function exits.

Explicit early release is also possible at the EHIR level through `drop`. The
Encore surface should only expose early release where the compiler can prove
that the value is not used afterward.

After a value has been dropped, using it again is a language error.

## Field Replacement

Replacing a reference field must preserve graph correctness.

Conceptually:

```enq
object.field = new_value
```

lowers to:

1. retain `new_value` for the field;
2. load the old field value;
3. store the new field value;
4. drop the old field value.

This order ensures that assigning the same value back into a field is safe and
that the old object is released exactly once.

Example:

```enq
struct Target {
    id: usize
}

struct Holder {
    target: Target
}

let old_target = Target{1_usize}
let holder = Holder{old_target}
let new_target = Target{2_usize}

holder.target = new_target
```

The old target is dropped from the field. If `old_target` is still live
elsewhere, the node remains allocated. If the field was the last reference, the
old target becomes eligible for cascading deallocation.

## Cascading Free And ERN

EHIR deallocates memory using graph reachability.

When the last reference to a node disappears, EHIR runs `cfree` for that node.
`cfree` does not blindly free every descendant. It frees only the nodes that are
exclusively reachable from the dropped node.

This set is called the ERN set: Exclusively Reachable Nodes.

Informally:

```text
ERN(v) = nodes reachable from v
         minus nodes that are also reachable from still-live roots
```

If a node is still reachable through another live object, it is not freed.

Example:

```enq
let target = Target{1_usize}
let a = Holder{target}
let b = target

drop a
```

Dropping `a` releases its edge to `target`, but `b` still points to the same
target node. Therefore the target node remains alive.

If `b` is later dropped too, the target node can be freed.

## Containers Are Not Special

Containers follow the same reference-type rule as every other aggregate.

```enq
let item = Node{10_usize}
let mut values = Vec[Node]::new()
values.push(item)
```

`Vec[Node]` is a reference node. `item` is also a reference node. Inserting the
item into the vector retains it for the vector storage.

When the vector is freed, it drops the references to its elements. If an element
is still referenced by another variable, that element stays alive.

```enq
let item = Node{10_usize}
let mut values = Vec[Node]::new()
values.push(item)

drop values

// item is still valid here because it has its own reference.
println(item.value)
```

There is no separate ownership model for "containers with heap elements". They
are just graph nodes with edges to other graph nodes.

## Strings

`str` is a reference type.

String literals and string operations produce string nodes:

```enq
let a = "he"
let b = a + "llo"
```

`a` points to the `"he"` string node. The concatenation creates a new `"hello"`
string node for `b`. When `a` is no longer used, its reference is dropped. When
`b` is no longer used, the `"hello"` node is dropped.

Encore does not need a separate user-facing `String` type for ordinary owned
text. The `str` type is the standard text resource.

## Enums And Tuples

Enums and tuples are reference types.

```enq
enum Option[T] {
    Some(T)
    None
}
```

`Option[Path]::Some(path)` stores an edge to the `Path` node. Matching the enum
retains payload values bound into local variables:

```enq
match maybe_path {
    Option[Path]::Some(path) => {
        println(path.as_str())
    }
    Option[Path]::None => {}
}
```

The payload binding `path` is dropped when the match arm exits.

## Function Boundaries

Function boundaries follow the same retain/drop rules.

Passing a reference argument:

```enq
fn len(value: Vec[u32]) -> usize {
    ret value.len()
}
```

The callee receives a retained reference. The callee drops its local reference
before returning. The caller's reference remains alive.

Returning a reference:

```enq
fn make_vec() -> Vec[u32] {
    let mut values = Vec[u32]::new()
    values.push(1_u32)
    ret values
}
```

The returned vector reference remains live in the caller. The compiler must not
drop the returned reference as a dead local.

## Native And Runtime Boundaries

Native functions that create or consume reference values must follow the same
ownership contract.

A native function returning `str`, `Vec[T]`, a file handle or another aggregate
returns a live reference node. The caller owns one reference and must eventually
drop it.

A native function receiving a reference type receives a retained reference. It
must not store that reference beyond the call unless the ABI explicitly says it
retains or transfers it.

Backend and build-script integrations must describe native ownership clearly.
The memory model cannot be correct if native code returns raw buffers whose
ownership is not specified.

## What This Means For Users

For new Encore users, the practical rules are:

- primitives behave like numbers in C or Rust;
- structs, enums, tuples, strings and vectors behave like shared objects;
- assigning an aggregate does not clone it;
- passing an aggregate to a function does not invalidate the caller's value;
- mutating an aggregate can be observed through all references to that object;
- use explicit clone APIs when an independent copy is needed;
- the compiler releases references automatically.

Example:

```enq
let mut first = Vec[u32]::new()
let second = first

second.push(10_u32)

// first and second point to the same Vec node.
println(first.len()) // 1
```

This is expected behavior.

## What This Means For Compiler Work

Compiler passes and coding agents should treat the following rules as
non-negotiable invariants.

1. Primitive types are value types.
2. Every aggregate type is a reference type.
3. Every reference type is represented as a graph node through hidden `Box`.
4. Assignment of a reference type emits retain.
5. Function argument passing of a reference type emits retain.
6. Field access of a reference type emits retain.
7. `for` loop element binding of a reference type emits retain for the loop
   variable.
8. Leaving scope emits drop for every live reference local that is not returned
   or otherwise transferred.
9. Field replacement retains the new value and drops the old value.
10. `cfree` frees only the ERN set, not every descendant blindly.
11. Containers are normal reference nodes and must not receive special ownership
    rules.
12. User-facing code should not expose hidden `Box` unless the API explicitly
    works with low-level EHIR concepts.

If a fix requires adding a special case for `str`, `Vec`, `Option`, a particular
module path or a particular test name, the fix is probably wrong. The correct
place to solve memory behavior is the general ValueType/ReferenceType lowering,
retain/drop placement or EHIR graph deallocation logic.

## Debugging Memory Issues

Memory bugs should be reduced to graph behavior:

- Which reference nodes exist?
- Which edges exist between them?
- Which variables are live roots?
- Which operation retains a reference?
- Which operation drops a reference?
- Which node starts `cfree`?
- Which nodes are in the ERN set?

Useful validation tools include:

- `--trace-cfree` to inspect deallocation order and released nodes;
- `valgrind` to detect leaked native allocations;
- regression tests with shared nodes, field replacement, nested structures and
  containers of reference values.

A good memory regression test should check both cases:

1. the old node is freed when no other reference exists;
2. the old node remains alive when another reference still points to it.

For example, when replacing `a.b.c.target`, test both:

```enq
a.b.c.target = Target{2_usize}
```

and:

```enq
let saved = a.b.c.target
a.b.c.target = Target{2_usize}
println(saved.id)
```

The first case should free the old target. The second case must keep it alive
until `saved` is dropped.

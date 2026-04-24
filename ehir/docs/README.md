# EHIR How To

EHIR is safe by default. Functions and structs are checked unless they have
`#attr(safe)`, which means the author promises that unsafe internals are wrapped
as a safe abstraction.

## Common Syntax

```ehir
#attr(safe)
pub fn name(arg: Type) -> Ret {
  $entry:
    out: Ret = ...
    ret out: Ret
}
```

Types:

```ehir
u1 u8 u16 u32 u64 usize
i8 i16 i32 i64 isize
f32 f64
char
str
T
T*
Box[T]
```

## Attributes

### `#attr(safe)`

Allowed on `fn`, `extern fn`, and `struct`.

For functions, permits unsafe instructions and `unsafe call`.

For structs, permits raw pointer fields.

### `#attr(inline)`

Allowed on `fn` and `extern fn`. This is an optimization hint.

## Directives

### `imp`

Imports an EHIR symbol.

```ehir
imp core::smart_box::Box
imp module::submodule::symbol
imp module::*
```

### `cimp`

Compile/import directive with the same path shape as `imp`.

```ehir
cimp std::io::println
```

### `type`

Compile-time type alias.

```ehir
type bool = u1
type MyWord = u32
```

### `extern fn`

Declares an external function. Calls to extern functions must use `unsafe call`.

Built-in `print(text: str) -> ()` and `eprint(text: str) -> ()` are injected by
the compiler as safe externs, so they can be called with plain `call`.

```ehir
extern fn puts(text: str) -> u32
```

### `struct`

Defines a structure. Fields are private by default. Use `pub` for externally
modifiable/readable fields.

```ehir
#attr(safe)
pub struct Box[T] {
  ptr: T*
  pub len: usize
}
```

Raw pointer fields require `#attr(safe)`.

### `enum`

Defines an enum. Variants may have one payload type.

```ehir
enum Option[T] {
  Some(T)
  None
}
```

### `trait`

Defines trait methods.

```ehir
trait Add[Rhs] {
  fn op(self: Self, rhs: Rhs) -> Self
}
```

Bounds:

```ehir
trait Fold[T] where T: Add + Scale {
  fn fold(lhs: T, rhs: T) -> T
}
```

### `impl`

Trait impl:

```ehir
impl Add[u32] for u32 {
  fn op(self: u32, rhs: u32) -> u32 {
    $entry:
      out: u32 = add self: u32, rhs: u32
      ret out: u32
  }
}
```

Inherent impl:

```ehir
impl[T] Box[T] {
  pub fn wrap(value: T) -> Box[T] {
    ...
  }
}
```

### `fn`

Defines a function.

```ehir
fn add(lhs: u32, rhs: u32) -> u32 {
  $entry:
    out: u32 = add lhs: u32, rhs: u32
    ret out: u32
}
```

## Instructions

Instruction forms are either assignable:

```ehir
out: Type = instruction ...
```

or terminator/standalone:

```ehir
ret value: Type
br $label
store value: T, ptr: T*
```

## Capture Instructions

### `capprim`

Safe. Creates a local primitive value.

```ehir
value: u32 = capprim 42_u32
text: str = capprim "hello"
letter: char = capprim 'a'
```

### `capstruct`

Safe. Creates a local struct value.

```ehir
point: Point = capstruct Point(x: u32, y: u32)
```

### `capenum`

Safe. Creates a local enum value.

```ehir
none: Option[u32] = capenum Option[u32]::None()
some: Option[u32] = capenum Option[u32]::Some(value: u32)
```

### `cpos`

Unsafe. Captures a primitive into raw pointer storage.

```ehir
ptr: u32* = cpos 10_u32
```

### `cstruct`

Unsafe. Captures a struct into raw pointer storage.

```ehir
ptr: Point* = cstruct Point(x: u32, y: u32)
```

### `cenum`

Unsafe. Captures an enum into raw pointer storage.

```ehir
ptr: Option[u32]* = cenum Option[u32]::Some(value: u32)
```

### `scpos`

Unsafe legacy smart-pointer capture for primitive values.

```ehir
value: Box[u32] = scpos 10_u32
```

### `scstruct`

Unsafe legacy smart-pointer stack capture for structs.

```ehir
point: Box[Point] = scstruct Point(x: u32, y: u32)
```

## Arithmetic Instructions

All arithmetic instructions are safe.

### `add`

```ehir
out: T = add lhs: T, rhs: T
```

### `sub`

```ehir
out: T = sub lhs: T, rhs: T
```

### `mul`

```ehir
out: T = mul lhs: T, rhs: T
```

### `div`

```ehir
out: T = div lhs: T, rhs: T
```

### `mod`

```ehir
out: T = mod lhs: T, rhs: T
```

### `shl`

```ehir
out: T = shl lhs: T, rhs: T
```

### `shr`

```ehir
out: T = shr lhs: T, rhs: T
```

## Logic And Comparison Instructions

These instructions are safe.

### `and`

```ehir
out: T = and lhs: T, rhs: T
```

### `or`

```ehir
out: T = or lhs: T, rhs: T
```

### `xor`

```ehir
out: T = xor lhs: T, rhs: T
```

### `ieq`

Integer equality. Returns `u1`.

```ehir
out: u1 = ieq lhs: T, rhs: T
```

### `neq`

Not equal. Returns `u1`.

```ehir
out: u1 = neq lhs: T, rhs: T
```

### `les`

Less-than. Returns `u1`.

```ehir
out: u1 = les lhs: T, rhs: T
```

### `leq`

Less-or-equal. Returns `u1`.

```ehir
out: u1 = leq lhs: T, rhs: T
```

### `grt`

Greater-than. Returns `u1`.

```ehir
out: u1 = grt lhs: T, rhs: T
```

### `geq`

Greater-or-equal. Returns `u1`.

```ehir
out: u1 = geq lhs: T, rhs: T
```

## Control-Flow Instructions

### `call`

Safe for EHIR functions. Extern functions require `unsafe call`.

```ehir
out: Ret = call fn_name(arg: Type)
out: Ret = call Type::method[T](arg: Type)
out: Ret = unsafe call extern_fn(arg: Type)
```

### `ret`

Safe. Returns from the current function.

```ehir
ret value: Type
```

### `br`

Safe. Unconditional branch.

```ehir
br $target
```

### `cbr`

Safe. Conditional branch on `u1`.

```ehir
cbr cond: u1, $then, $else
```

### `switch`

Safe. Primitive switch.

```ehir
switch value: usize, $default {
  0_usize => $zero
  1_usize => $one
}
```

### `match`

Safe. Enum match.

```ehir
match value: Option[u32], $default {
  Some(payload: u32) => $some
  None => $none
}
```

### `phi`

Safe. SSA phi.

```ehir
out: T = phi left: T $left_block, right: T $right_block
```

## Memory Instructions

### `salloc`

Unsafe. Allocates stack storage.

```ehir
ptr: T* = salloc T
```

### `halloc`

Unsafe. Allocates heap storage for one value.

```ehir
ptr: T* = halloc T
```

### `hrealloc`

Unsafe. Reallocates heap storage for `count` values.

```ehir
new_ptr: T* = hrealloc old_ptr: T*, count: usize
```

### `hfree`

Unsafe. Frees heap storage.

```ehir
hfree ptr: T*
```

### `load`

Unsafe. Loads through a raw pointer.

```ehir
value: T = load ptr: T*
```

### `store`

Unsafe. Stores through a raw pointer.

```ehir
store value: T, ptr: T*
```

### `put`

Unsafe. Writes a primitive into a pointer.

```ehir
put 1_u32, ptr: u32*
```

### `pcast`

Unsafe. Casts a value to a pointer/type.

```ehir
ptr: T* = pcast raw: usize, T*
```

### `getptr`

Unsafe. Gets a raw pointer to a value.

```ehir
ptr: T* = getptr value: T
```

### `getfield`

Safe. Reads a struct/enum field by name or index.

```ehir
value: T = getfield src: Struct, field_name
value: T = getfield src: Struct, 0
```

### `getfieldptr`

Unsafe. Gets a raw pointer to a field.

```ehir
ptr: T* = getfieldptr src: Struct*, field_name
```

### `gep`

Unsafe. Pointer arithmetic.

```ehir
elem_ptr: T* = gep base: T*, index: usize
```

### `sgetfield`

Unsafe legacy smart-pointer field read.

```ehir
value: T = sgetfield src: Box[Struct], field_name
```

### `sgetfieldptr`

Unsafe legacy smart-pointer field pointer access.

```ehir
ptr: T* = sgetfieldptr src: Box[Struct], field_name
```

### `pload`

Unsafe post-lowering pointer load form.

```ehir
value: T = pload ptr: T*
```

## Special Instructions

### `cfree`

Unsafe internal cascade-free primitive. User code should prefer generated
`Drop`/core abstractions.

```ehir
cfree value: T
```

### `comment`

Internal/comment instruction. Text files usually use `;` line comments instead.

```ehir
; comment text
```

## Safety Summary

Safe instructions:

```text
capprim capstruct capenum
add sub mul div mod shl shr
and or xor ieq neq les leq grt geq
call ret br cbr switch match phi
getfield
```

Unsafe instructions:

```text
cpos cstruct cenum
scpos scstruct sgetfield sgetfieldptr
salloc halloc hrealloc hfree
load store put pcast getptr getfieldptr gep pload cfree
unsafe call
```

Unsafe instructions require the enclosing function to have `#attr(safe)`.
Raw pointer fields require the enclosing struct to have `#attr(safe)`.

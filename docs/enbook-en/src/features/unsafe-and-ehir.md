# Unsafe Code and Embedded EHIR

`unsafe` marks operations whose invariants cannot be proven by ordinary
Encore checking, including native extern calls. Keep unsafe blocks small and
document the caller-visible invariant.

## Inferred function safety

An `unsafe` block does **not** contain the effect at the block boundary. A
function containing it is unsafe to its callers. Calling an unsafe function
also makes the caller unsafe, transitively, including recursive call chains,
imports, aliases, methods and implicit protocol calls. No additional keyword
is required at each call site: the compiler infers the effect.

`#attr(safe)` is the explicit trust boundary:

```encore
fn raw_value() -> u32 {
    unsafe { ret 42_u32 }
}

fn unchecked() -> u32 { ret raw_value() } // inferred unsafe

#attr(safe)
fn checked() -> u32 { ret raw_value() } // safe contract for callers
```

The annotation means the author accepts responsibility for the entire
implementation, including calls. It does not prove that the implementation is
correct. Without it, a wrapper around a native call is not automatically safe.
Extern declarations and abstract methods without a safe contract are unsafe.

Creating a closure does not execute its body. Its effect propagates when the
closure is invoked, not when it is created. Known function aliases and returned
closures preserve their effects. Unknown callbacks, mutable callable captures
and unresolved dispatch are conservatively unsafe; inference does not promise
effect-polymorphic specialization for every possible callback argument.
Decorated functions are conservatively unsafe unless explicitly trusted.
Embedded EHIR is opaque to this source-level analysis and likewise requires an
explicit safe boundary when exposed as a safe API.

Use `encore check --safety` to inspect contracts, or add `--format json` for
structured records. LSP callable hover uses the same semantic query. Ordinary
checking does not reject a function merely because it is inferred unsafe.

```encore
{{#include ../../examples/guide/src/features/mod.enq:unsafe}}
```

`ehir { ... }` and `unsafe ehir { ... }` embed EHIR instructions for compiler
and systems work. EHIR is an independent compiler IR and abstract machine;
Encore is one high-level frontend that lowers into it.

## Native calls need an ABI contract

An `extern fn` declares a symbol; it does not implement that symbol or arrange
for a library to be linked. The clock fragment above relies on the matching
Encore platform runtime. It is not a portable declaration of an arbitrary
system C function. Configure native sources and libraries through
[build metadata](../packages.md#native-build-scripts).

Match argument/result representation, calling convention, target integer
widths, and ownership expectations on both sides. `str` is not a C
NUL-terminated `char*`. A `T&` is an owning graph handle, not a C pointer to an
inline payload. Do not "fix" a native signature by casting until it compiles.

For raw pointers, establish who allocates and frees storage, how long it stays
valid, its alignment and bounds, and whether another thread may access it.
For stack handles, prove the callee cannot retain or return an escaping handle.
An `unsafe` block records where a proof is required; it does not manufacture
that proof or disable all language checking.

Keep the native declaration private and expose a small `#attr(safe)` wrapper only when
the wrapper can enforce its documented preconditions. Test that wrapper on
each supported ABI. Embedded EHIR is an advanced implementation tool, not the
first remedy for a missing high-level API.

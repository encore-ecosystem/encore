# Loops, Ranges, and Labels

Use `for value in start..end` for an exclusive range and `..=` for an
inclusive one. `while`, `do ... while`, and `loop` cover condition-driven and
unbounded iteration. Labels let `break` and `continue` target an outer loop.

Range bounds have type `usize`. Convert narrower integer values explicitly,
for example `0..(items.count() as usize)` when `count()` returns `u32`.

```encore
{{#include ../../examples/guide/src/features/mod.enq:loops}}
```

The sample's exclusive upper bound makes `sum(4)` add 0, 1, 2, and 3. An
inclusive range also visits its endpoint. A `while` body may execute zero
times; a `do ... while` body executes before its condition is checked.
`break` leaves its target loop, while `continue` advances that loop's control
flow. A label distinguishes the intended loop in nested traversal.

For collections, `for` uses the iterator protocol rather than promising indexed
access. Avoid mutating an iterated collection unless that iterator's API
explicitly supports it. For manual indices, check bounds before access and
consider empty input and the largest valid endpoint.

**Exercise:** what does `sum(0)` return? Zero: the exclusive range is empty.
Turning every `..` into `..=` would change that boundary behavior.

## Generators

A function containing `yield` creates a lazy `core::iter::Generator[T]`.
Its written return type is the type of each yielded item:

```encore
fn fibonacci(count: usize) -> usize {
    let mut previous = 0_usize
    let mut current = 1_usize
    for _ in 0..count {
        let value = previous + current
        yield value
        previous = current
        current = value
    }
}

for value in fibonacci(5) {
    println(f"{value}") // 1, 2, 3, 5, 8
}
```

Arguments are evaluated when calling the function. Its body starts on the first
`next` and resumes after each `yield`, preserving locals and control flow.
`ret ()` or reaching the end completes the generator; subsequent `next` calls
return `None`. A generator cannot return a separate completion value.

Copies share one cursor. If `let alias = generator` copies a generator, consuming
one alias advances the other. Separate calls to the function create independent
generators. `Generator[T]` implements the ordinary `Iterator[T]` protocol:
`next(self) -> (Self, Option[T])`; the returned `Self` shares the same cursor.

A `with` context stays open while execution is suspended inside it. Normal scope
exit closes the context. Abandoning the final owning reference closes active
contexts in reverse nesting order without executing the remaining function body.
`break` only stops that consumer: another alias can continue the generator.
Cleanup occurs at the owning handles' last use under Encore's memory model,
including when an otherwise unreachable cycle is reclaimed.

Generators are confined to their creating thread. Recursive calls into an
executing or closing generator panic. The initial protocol supports `yield expr`
in named synchronous functions and methods; `yield from`, `send`, explicit
`close`, and asynchronous generators are not supported. Use `match` to handle
`Result` in a generator and yield result values when callers need an error item.

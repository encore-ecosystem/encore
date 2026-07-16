# Concurrency

Encore provides native operating-system threads for CPU-parallel work. A
thread is started by applying `spawn` to a direct Encore function call:

```enq
fn square(value: u64) -> u64 {
    ret value * value
}

fn main() -> u32 {
    let left = spawn square(12_u64)
    let right = spawn square(15_u64)
    let total = left.join() + right.join()
    ret if total == 369_u64 { 0_u32 } else { 1_u32 }
}
```

`spawn function(args...)` moves an owned copy of every argument into a native
thread and returns `JoinHandle[T]`. Calling `join()` blocks until that thread
finishes and moves its result back to the caller. A handle can be joined only
once. Dropping an unjoined handle performs a structured join and drops the
result, so a thread cannot outlive the scope that owns its handle.

Values crossing a thread boundary must be structurally safe to send. Numeric
values, booleans, strings, tuples, arrays, vectors, enums, and value structs
are accepted when all their elements are safe. Mutable references, raw
pointers, heap/stack pointers, dynamic trait objects, and thread handles are
rejected. Reference counts used by strings and copy-on-write aggregates are
atomic across threads.

Use `core::thread::available_parallelism()` to inspect the number of logical
processors available to the process. Native threads are intended for CPU
parallelism and blocking work. `async`/`await` remains the lightweight model
for cooperative tasks and does not create an operating-system thread by
itself.

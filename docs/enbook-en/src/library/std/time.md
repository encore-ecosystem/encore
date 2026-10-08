# `std::time`

Re-exports wall-clock milliseconds, monotonic performance counters in
milliseconds or nanoseconds, and sleeping.

`Duration::from_secs`, `from_millis` and `from_nanos` construct nonnegative
durations. `as_secs()` truncates fractional seconds; `subsec_nanos()` returns
the fractional part. `as_secs_f64()` includes it. `as_millis()` and
`as_nanos()` return `Option[u64]`, with `None` on overflow. `checked_add` and
`checked_sub` return `None` on overflow or a negative result.

`Instant::now()` captures a monotonic reading, not a wall-clock timestamp.
`instant.elapsed()` returns a `Duration` (saturating to zero if the clock
moves backwards). `later.duration_since(earlier)` returns `Option[Duration]`.

```encore
{{#include ../../../examples/guide/src/std_examples/mod.enq:time}}
```

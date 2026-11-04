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

## Clock domains and timers

`SystemClock::new()` returns an owned `Clock` backed by monotonic system time.
Each system clock has one scheduler thread. Copies share its domain and timer
queue. `VirtualClock::new()` creates a domain starting at zero; its `clock()`
returns the same `Clock` API without a scheduler thread. Virtual time advances
only through `advance(duration)` and never follows wall time.

`clock.now()` returns a `ClockInstant`. `duration_since` rejects different
domains with `ClockError::MismatchedClock` and backwards subtraction with
Overflow. `clock.sleep(duration)` and `sleep_until(deadline)` return
`Result[Timer, ClockError]`; a timer implements `Future[Result[(), ClockError]]`.
Duration conversion, deadline addition, and virtual advances check overflow.
Equal-deadline virtual timers become ready in registration order. Advancing
time makes timers ready without executing Encore code inside the advance.

`timer.cancel()` wakes its waiters with Cancelled. Dropping a pending timer
unlinks its registration. `clock.close()` wakes outstanding timers with Closed
and joins a system scheduler exactly once. Copies observe the same shutdown.
Use a `with` context to close a clock on scope exit; final-owner drop also
cleans up the native state. A timer retains its clock until it is released.

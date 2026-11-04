# `std::future`

Re-exports the core future protocol and adds `block_on`, the synchronous
executor boundary for a concrete `Future[T]`.

```encore
{{#include ../../../examples/guide/src/features/mod.enq:async}}
```

`Context` contains an owned `Waker`. Copies retain its wakeup target, and dropping
one copy does not invalidate another. A future may store a copy while pending;
release it when the registration ends. `block_on` owns its executor event until
the last retained waker is released. Wakeups may coalesce.

## Readiness races

`Selector::new()` creates a shared round-robin selector. Its `select2` and
`select3` methods rotate the first-polled branch across calls. They return
`Select2[A, B, T, U]` or `Select3[A, B, C, T, U, V]`. The completed
`Selected2`/`Selected3` variant contains the winning output and every unfinished
future. Polling a race does not spawn or detach work. Retain, resume, cancel, or
drop those futures explicitly. Fairness applies to branches which are ready
when polled; it does not preempt a blocking `poll` implementation.

`timeout(clock, duration, future)` uses an explicit `std::time::Clock`. Its
`TimeoutFuture[F, T]` yields `TimeoutOutcome[F, T]`:

- `Ready(T)` when the operation completes;
- `Elapsed(F)` when the timer wins;
- `ClockFailed((F, ClockError))` when the clock closes or the timer is cancelled.

Timer setup failure returns `TimeoutError[F]` with `future` and `error` fields.
Neither setup failure nor expiry discards the pending operation. For a pending
channel send, `into_unsent()` recovers its uncommitted payload.

`cancellable(future, token)` returns a `CancellationFuture[F, T]` whose outcome
is `Ready(T)` or `Cancelled(F)`. Cancellation preserves the unfinished future;
dropping that future performs the operation's own cleanup. Timeout and
cancellation races poll the operation first when both branches are ready.


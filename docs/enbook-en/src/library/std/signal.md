# `std::signal`

`Signals::subscribe()` owns a coalescing subscription to SIGINT and SIGTERM.
It returns Unsupported on unsupported targets, InUse when a subscription or
existing nondefault handler already owns these signals, or AllocationFailed
if native setup cannot complete. The initial Windows implementation returns
Unsupported.

`next()` provides a `SignalFuture`; `wait()` blocks using the same wakeup
mechanism. Successful values are `Signal::Interrupt` and `Signal::Terminate`.
Repeated signals may coalesce while delivery is pending.

A subscription may be used in a `with` context. `close()` wakes waiters with
Closed, restores handlers still owned by this subscription, and joins its
native delivery worker. Final-owner drop performs the same cleanup. Closing
again is harmless. Signal handling writes to a nonblocking pipe; Encore
callbacks execute outside the native signal handler.

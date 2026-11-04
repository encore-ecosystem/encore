# `std::sync`

Synchronization handles own their native state. Copying a sender, atomic cell,
mutex, cancellation token, frozen snapshot, or watch endpoint shares that state.
A receiver requires exclusive `sending` transfer between threads. An active
mutex guard stays on its locking thread. End its lexical scope before `await`;
the compiler conservatively rejects a live guard value even after `release()`.

## Bounded channels

`bounded[T](capacity)` creates a bounded MPSC queue. Capacity must be positive.
Copy the sender, then consume the pair with `into_receiver` when moving its
receiver to a worker:

```encore
import core::result::Result
import std::sync::{Receiver, Sender, bounded, into_receiver}

fn consume(input: sending Receiver[str]) -> u32 {
    ret if input.receive_blocking().unwrap_or("") == "ready" { 0_u32 } else { 1_u32 }
}
fn main() -> u32 {
    let pair = match bounded[str](8_usize) {
        Result::Ok(value) => value
        Result::Err(_) => { ret 1_u32 }
    }
    let sender = pair.0
    let input = into_receiver[str](pair)
    let worker = spawn consume(input)
    if sender.send_blocking("ready").is_err() { ret 2_u32 }
    ret worker.join()
}
```

Send operations accept `sending T`: inline values are supported, and mutable
regions must satisfy the language's exclusive-transfer checks. `Frozen[T]`
allows shared immutable payloads.

| Operation | Result |
| --- | --- |
| `Sender.try_send(value)` | Immediate success, Full, or Closed |
| `Sender.send(value)` | A `SendFuture[T]` with backpressure |
| `Sender.send_cancellable(value, token)` | A send future observing cooperative cancellation |
| `Sender.send_blocking(value)` | Waits without a polling sleep |
| `Receiver.try_receive()` | A value, Empty, or Closed |
| `Receiver.receive()` / `receive_cancellable(token)` | A receive future |
| `Receiver.receive_blocking()` | Waits for a value or closure |

`SendError[T]` contains its kind and an `Option[T]` with the uncommitted value.
A full, closed, or cancelled fresh send returns that value. A repeated alias
which has already committed or recovered its payload reports AlreadyCompleted
with None. Enqueue and recovery transfer a payload once.

`close()` wakes waiters. Closing the receiver discards queued values and makes
senders observe Closed. After the final sender closes, the receiver can drain
queued values before observing Closed. Dropping an endpoint closes it when its
last owner disappears. Dropping a pending operation removes its registrations.
Receive futures remain local to their consumer thread.

Timeout returns the unfinished send future; call `into_unsent()` to recover a
payload that has not committed. If another alias committed it, recovery returns
None. Timeout itself does not silently discard the unfinished operation.

## Atomic cells

`AtomicBool` and `AtomicU64` provide sequentially consistent `load`, `store`,
`swap`, and `compare_exchange`. Compare-exchange returns `Ok(previous)` on
success or `Err(actual)` on failure. `AtomicU64` also provides `fetch_add`,
`fetch_sub`, `fetch_and`, `fetch_or`, and `fetch_xor`; these return the previous
value. Copies refer to the same cell.

## Guarded ownership

`Mutex[T]::new(value)` takes a `sending T`. `try_lock()` returns a guard or
WouldBlock; recursive locking on the same thread returns WouldDeadlock.
`lock()` blocks and `lock_async()` provides a future.

The guard manages an optional owned slot. `take()` removes its value;
`replace(value)` installs an exclusively transferred value and returns the old
one. This supports mutable graph values without allowing a mutable reference
to escape beyond the guard. Leaving the slot empty is an explicit supported
state. A released guard returns Released from `take`; a failed `replace`
returns the supplied value through `GuardError[T]`.

Use `with guard as locked { ... }`, explicit `release()`, or final-owner drop
to unlock. Release is idempotent, including through copied guards. A guard
released through one alias cannot access the slot through another alias.

## Frozen snapshots and watch

`Frozen[T]::new(value)` requires a `frozen T`. Its `get()` returns a recursively
immutable view that retains the snapshot's storage. Multiple threads may read
it. Construct synchronization handles through their typed SDK APIs.

`watch(initial: Frozen[T])` creates a writer and reader. A reader's `snapshot()`
returns the current `WatchSnapshot[T]` containing `version` and `value`.
`changed(after)` waits until a newer version exists or the writer closes.
Readers may skip intermediate versions; previously obtained snapshots keep
their original contents. Publishing increments the version with overflow
checking. Writer closure wakes waiting readers; the last snapshot stays
readable. Watch endpoints and immutable snapshots may be shared across threads.

## Cancellation

`CancellationToken::new()` creates an independent token. `child()` creates a
token cancelled by its parent or any ancestor. Cancelling a child does not
cancel its parent or siblings. Cancellation is permanent and idempotent;
dropping a token does not request cancellation.

Use `is_cancelled()`, blocking `wait()`, or the `cancelled()` future. Waiting
registrations retain the relevant state and waker, and unlink on drop. The
cancellation/select and timeout helpers in `std::future` return unfinished
futures so callers can retain, resume, recover, or drop them explicitly.

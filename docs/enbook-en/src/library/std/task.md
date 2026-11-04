# `std::task`

`TaskGroup[Job, Output]` owns a bounded set of operating-system workers and
bounded per-worker input queues. It uses the existing `spawn` model and
cooperative `CancellationToken` contract.

Implement the job protocol with an owned result:

```encore
import core::result::Result
import std::sync::CancellationToken
import std::task::TaskJob

struct Square { value: u64 }
impl TaskJob[u64] for Square {
    pub fn run(self: Self, token: CancellationToken) -> sending Result[u64, str] {
        ret Result::Ok(self.value * self.value)
    }
}
```

`TaskGroup[Square, u64]::new(workers, capacity)` uses CancelOnError. Both counts
must be positive, and the initial implementation supports at most 256 workers.
`with_policy(workers, capacity, TaskPolicy::CollectAll)` continues after job
errors. A job receives a child token and should observe cancellation during
long-running work.

`try_submit(job)` returns a submission ID or Full, Closed, Cancelled, or
IdExhausted, preserving an unsubmitted job. `submit(job)` waits for capacity
while collecting completions, which prevents a full completion queue from
blocking submission permanently. Submission IDs are allocated on successful
submission and determine the final result order.

`join()` closes submission and returns `GroupJoinFuture[Job, Output]`. Its
output is `Result[Vec[TaskResult[Output]], TaskError]`. Every accepted job has an
ID and a Completed, Failed, or Cancelled outcome. Results are ordered by ID
regardless of worker completion order. A repeated join alias reports Closed
instead of publishing mutable result graphs twice.

Pass the join future to `std::future::timeout` to apply a deadline. Elapsed
returns the owning join future, whose `into_group()` retains the pending
workers for later cancellation or join. A deadline never detaches workers.

`cancel()` requests cancellation while preserving completion collection.
Dropping the last group owner cancels work, closes its queues, and joins all
workers before releasing their state. Jobs must cooperate with cancellation;
ordinary structured joining still waits for a job which does not finish.
The group and its join future remain on their owning thread.

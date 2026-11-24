# Asyncio

`@asyncio.main` starts a runtime around `async fn main() -> u32` and uses its result as the process exit code. `asyncio::current()` gives the running task a handle to its runtime.

`Runtime::new` configures async workers, blocking workers and queue capacity. `spawn_task` schedules a transferable future and returns an awaitable `TaskHandle`. `spawn_blocking` accepts a future whose poll can block and schedules it on the separate blocking pool. Each task stays on its assigned worker.

A task handle can request cancellation. `Runtime::shutdown` closes the queues, cancels async work and joins the workers. Blocking code already executing runs until it returns. Call `shutdown` when using the explicit runtime API.

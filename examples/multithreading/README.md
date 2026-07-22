# Multithreading

This example first starts two native workers which both sleep for one second.
Their timestamps and the total duration make it visible that the waits overlap.
It then divides CPU work between another pair of threads. `spawn` transfers the
arguments and `join()` waits and moves each typed result back.

```sh
encore run --profile release
```

Typical output (CPU count and timing depend on the machine):

```text
logical CPUs available: 16

sleep demo: two workers sleep for 1000 ms concurrently
worker A: sleeping at +0 ms
worker B: sleeping at +0 ms
worker A: awake at +1000 ms
worker B: awake at +1000 ms
joined worker A and worker B
total sleep phase: 1000 ms (not 2000 ms)

CPU demo: spawning two range-sum workers
sum(1..20,000,000) = 200000010000000
CPU parallel section: 12 ms
```

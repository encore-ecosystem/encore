# Multithreading

This example divides CPU work between two native operating-system threads.
`spawn` transfers the arguments to each worker and returns `JoinHandle[u64]`;
`join()` waits and moves the result back.

```sh
encore run --profile release
```

Typical output (CPU count and timing depend on the machine):

```text
logical CPUs available: 16
spawning two native worker threads
sum(1..20,000,000) = 200000010000000
parallel section: 12 ms
```

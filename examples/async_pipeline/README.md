# Async Pipeline

This example implements a small future which returns `Pending` once, wakes the
executor, and then returns `Ready`. The async pipeline awaits two such futures.

```sh
encore run
```

The output makes lazy execution and every poll transition visible:

```text
main: creating future (the body is still lazy)
main: entering block_on
pipeline: started on first poll
  load-left: Pending (wake executor)
  load-left: Ready(20)
pipeline: first await completed
  load-right: Pending (wake executor)
  load-right: Ready(22)
pipeline: second await completed
main: result = 42
```

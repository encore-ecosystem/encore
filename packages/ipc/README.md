# IPC

`ipc::LocalListener` and `ipc::LocalStream` provide binary byte streams over Unix domain sockets. The blocking and asynchronous APIs use deadlines from the shared network reactor.

Place the socket in a directory accessible to the intended peers. The caller owns the pathname and removes it after closing the listener. `shutdown_write` sends EOF to the peer while leaving the read side open. Await outstanding writes before calling it. An empty successful read with a positive limit indicates EOF.

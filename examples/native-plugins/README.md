# Native Formatter plugin

The `api` package is the shared contract. Each plugin and the host compiles its
own runtime; only the versioned C ABI crosses the library boundary.

Build each package with the compiler from this branch:

```sh
(cd formatter-v1 && encore build)
(cd formatter-v2 && encore build)
(cd host && encore build)
PLUGIN_V1="$PWD/formatter-v1/target/dev/libformatter_plugin.so" \
PLUGIN_V2="$PWD/formatter-v2/target/dev/libformatter_plugin.so" \
  host/target/dev/formatter_host
```

Use `.dylib` on macOS and `formatter_plugin.dll` on Windows. The paths may
contain spaces or Unicode. The host keeps the same `Binding[dyn Formatter]`
while replacing the implementation. Calls return `Result[T, PluginError]`.

`Plugin::load` and `reload` require an `unsafe` block because native libraries
have the same process privileges as the host. Load only trusted binaries.
A plugin must not leave untracked native threads running after its final object
is destroyed. Root bindings switch at reload; returned resources retain their
original generation until released. A failed replacement leaves the current
bindings usable. `close` returns Busy while any bindings or resources remain.

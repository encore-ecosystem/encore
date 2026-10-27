# Native Plugins

A native plugin is a shared library with a typed Encore interface. The host and
provider compile their own runtimes. Values cross a versioned C ABI, and each
runtime releases its own allocations. Linux uses `.so`, macOS uses `.dylib`, and
Windows uses `.dll`.

Loading and replacing native code requires `unsafe`: plugins have the host
process's privileges. Use binaries you trust. A plugin must finish its native
background work before its final objects are released.

## Declare the contract

Put the public contract in a package shared by the host and provider:

```encore
#attr(plugin_interface)
pub trait Formatter {
    fn format(self: Self, source: str) -> str
}
```

Methods are synchronous instance methods without method-level generic
parameters. Generic interfaces can be bound with concrete arguments, such as
`Binding[dyn Echo[Document]]`. Base traits are not supported in ABI v1.

Supported data includes integers up to 64 bits, usize/isize, f32/f64, bool, str,
Vec, fixed arrays, tuples, structs,
enums, Option, Result, and `Resource[dyn Interface]`. Enum variants have zero or
one payload; group multiple fields into a struct or tuple. Raw pointers, nodes,
capabilities, plain dyn values, and module/binding handles cannot be DTOs.
Reflected fixed arrays are limited to 65,536 elements.

## Build the provider

Implement the trait and define a synchronous factory returning
`Result[ConcreteImplementation, str]`. Declare its export in `encore.toml`:

```toml
[project]
name = "formatter_plugin"
version = "1.0.0"
target = "shared_lib"
dependencies = ["path@../api", "path@../../../packages/std"]

[plugin.exports.formatter]
interface = "formatter_api::Formatter"
factory = "create_formatter"
stateless = true
```

The implementation stays inside its provider and may own a heap graph. Factories
and resources can also use a heap node (`ConcreteImplementation<H>`) directly.
The compiler checks the exact implemented interface, including concrete generic
arguments.

Run `encore build`. The compiler generates the adapters and exports only
`encore_plugin_entry_v1`. Contract fingerprints describe interface and DTO
structure; implementation bodies and absolute checkout paths do not affect
compatibility.

For a stateful export, replace `stateless = true` with both hooks:

```toml
save-state = "save_formatter"
restore-state = "restore_formatter"
```

Their signatures are `(ConcreteImplementation) -> Result[StateSnapshot, str]`
and `(StateSnapshot) -> Result[ConcreteImplementation, str]`.
`StateSnapshot` contains a `version: u32` and `data: Vec[u8]`. The plugin defines
its snapshot format and validates versions during restore.

## Load, call, and replace

```encore
import formatter_api::Formatter
import std::plugin::{Plugin, PluginError}
import core::result::Result

fn format_once(path: str) -> Result[str, PluginError] {
    let plugin = unsafe { Plugin::load(path) }?
    let formatter = plugin.bind[dyn Formatter]("formatter")?
    ret formatter.format("hello")
}
```

Each proxy call adds an outer `Result[DeclaredReturn, PluginError]`. If the
interface itself returns `Result[Document, str]`, the call returns
`Result[Result[Document, str], PluginError]`.

`unsafe { plugin.reload(new_path) }` drains current calls, saves and restores
state, then switches existing root bindings together. A failed replacement
leaves those bindings on their original implementation. Calls execute serially
within a generation; libraries are loaded from separate immutable copies.

A provider creates a returned resource with
`Resource[dyn Interface]::new(concrete_value)`. Copies share its lifetime.
Returned resources keep their original generation across reload. Passing an
old resource to a new generation produces a wrong-generation error. The final
resource, binding, and call must be released before its library unloads.
Per-library static values are destroyed before unloading their generated code.

`close()` returns Busy while bindings, resources, or calls remain. Release
bindings in an inner scope before closing. Handles are opaque; construct them
through the SDK and use their methods.

`Plugin::load_with(path, PluginOptions::new())` allows configuring limits. The
defaults are 64 MiB per transfer, depth 128, two retained generations, and a
5,000 ms quiescence timeout. Depth limits can range from 1 to 256. A timeout
returns an error and keeps the current generation usable.

See the complete runnable [Formatter example](../../../../examples/native-plugins/README.md)
and the [public C ABI header](../../../../packages/platform/plugin_abi.h).

## Measure the boundary

Run the correctness tests and benchmarks with an Encore compiler built from
this source:

```sh
python3 scripts/test-native-plugins.py \
  --compiler "$PWD/target/extreme/encore" --benchmark \
  --report target/native-plugins/benchmarks.json
```

Benchmark mode builds the Encore providers and hosts with `extreme`. The report
contains a direct C ABI comparison for the native manager and separate full SDK
measurements for a typed scalar call, DTOs with 4 KiB and 1 MiB buffers, and
stateless reload with live bindings. Linux and macOS also record the SDK host's own
peak RSS. These are measurements, without a universal
latency threshold.

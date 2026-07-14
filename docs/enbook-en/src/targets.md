# Targets And Cross-Compilation

Encore separates the machine running the compiler (the host) from the machine
running the generated program (the target). A target is identified by an LLVM
compatible triple:

```text
<architecture>-<vendor>-<operating-system>-<environment>
```

The compiler accepts arbitrary triples. `encore target list` reports the
desktop targets for which release artifacts are produced; it is not a
whitelist. Inspect the host or another target with:

```sh
encore target
encore target thumbv7em-none-eabihf
```

Encore derives ABI properties such as pointer width from the architecture and
environment. An unknown architecture is rejected instead of being guessed as
32-bit; this prevents silently generating incompatible `usize`, `isize`, and
pointer layouts. ABI variants such as `gnux32`, `gnuabin32`, and `aarch64_32`
are classified independently from their 64-bit base architecture.

Build for a target with:

```sh
encore build --target aarch64-unknown-linux-gnu
```

Native artifacts remain under `target/<profile>`. An explicit cross-target is
written under `target/<triple>/<profile>` so artifacts for different devices
cannot overwrite each other.

## Toolchains

The default driver is `clang`. Configure defaults for every target and then
override individual triples in `encore.toml`:

```toml
[project]
name = "firmware"
target = "thumbv7em-none-eabihf"

[target]
linker = "clang"
ar = "llvm-ar"
builtin-runtime = false

[target.thumbv7em-none-eabihf]
linker = "arm-none-eabi-clang"
ar = "arm-none-eabi-ar"
sysroot = "/opt/arm-none-eabi"
cpu = "cortex-m4"
features = "+thumb2,+vfp4"
runtime-sources = ["platform/runtime.c", "platform/startup.c"]
linker-script = "platform/memory.ld"
compile-args = ["-mthumb"]
link-args = ["-nostdlib", "-Wl,--gc-sections"]
```

Command-line options have the highest priority:

```sh
encore build \
  --target aarch64-unknown-linux-gnu \
  --linker clang \
  --sysroot /opt/aarch64-sysroot \
  --target-cpu cortex-a72
```

The environment fallbacks are `ENCORE_CC`, `ENCORE_LINKER`, `ENCORE_AR`,
`ENCORE_SYSROOT`, `ENCORE_TARGET_CPU`, and `ENCORE_TARGET_FEATURES`.

## Output Kinds

Select an intermediate or final artifact with `--emit ehir`, `--emit llvm-ir`,
`--emit object`, or `--emit binary`. Hosted targets default to `binary`.
Freestanding targets default to `object`, which requires no runtime or linker.

A freestanding binary must configure `runtime-sources`. Hosted targets use the
bundled Encore runtime by default; set `builtin-runtime = false` when a target
provides its own runtime instead. `linker-script`, `compile-args`, and
`link-args` are resolved per target; relative source and script paths are
resolved from the project root. This keeps board support in the project or
platform package instead of hard-coding devices in the compiler.

## Conditional Compilation

`#cfg` is evaluated against the selected target, not the host:

```enq
#cfg(target_os = "linux")
fn platform_name() -> str { ret "linux" }

#cfg(all(target_arch = "arm", target_env = "eabihf"))
fn platform_name() -> str { ret "arm-eabihf" }
```

Available keys are `target_os`, `target_arch`, `target_env`, `target_family`,
`target_pointer_width`, and `target_endian`. Capability aliases include
`hosted`, `freestanding`, `unix`, `windows`, and `none`. Desktop, mobile,
WebAssembly, BSD, and bare-metal LLVM triples are classified independently;
for example, Android and iOS do not alias Linux and macOS in `target_os`.

Cross-compilation requires a linker and sysroot capable of producing binaries
for the requested target. Bare-metal targets additionally require a compatible
Encore runtime; the target model itself does not special-case STM32 or another
device family.

# Targets And Cross-Compilation

Encore separates the machine running the compiler (the host) from the machine
running the generated program (the target). A target is identified by an LLVM
compatible triple:

```text
<architecture>-<vendor>-<operating-system>-<environment>
```

The compiler accepts arbitrary triples. `encore target list` reports managed
and native targets; it is not a whitelist. Inspect or install a target kit:

```sh
encore target
encore target show thumbv7em-none-eabihf
encore target install aarch64-unknown-linux-gnu
```

Native release and CI targets currently cover Linux, macOS, and Windows on x86-64 and
AArch64, plus Windows on x86-64 (`x86_64-pc-windows-msvc`). Windows compiler
archives use ZIP and contain `bin/encore.exe`; Unix compiler archives use
`tar.gz` and contain `bin/encore`.

Encore derives ABI properties such as pointer width from the architecture and
environment. An unknown architecture is rejected instead of being guessed as
32-bit; this prevents silently generating incompatible `usize`, `isize`, and
pointer layouts. ABI variants such as `gnux32`, `gnuabin32`, and `aarch64_32`
are classified independently from their 64-bit base architecture.

Build for a target with:

```sh
encore build --target aarch64-unknown-linux-gnu
```

For a managed cross target, a missing kit is an error and the diagnostic prints
the exact install command. Kits are compiler-ABI-coupled, checksummed, installed
atomically under `~/.encore/targets`, and contain host tools plus target
sysroot/runtime/platform sources. Once installed, builds can run offline.

Guaranteed managed cross targets are Linux x86-64/AArch64 and Windows GNU
x86-64/AArch64. Darwin remains native because Encore does not redistribute
Apple SDKs. Windows MSVC remains a native target. A fully configured custom
toolchain remains available without a managed kit.

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
driver = "clang"
linker = "clang"
ar = "llvm-ar"
builtin-runtime = false

[target.thumbv7em-none-eabihf]
driver = "clang"
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

For one-off toolchain experiments, append arguments without changing the
manifest:

```sh
encore build --target aarch64-unknown-linux-gnu \
  --compile-arg -fno-omit-frame-pointer \
  --link-arg -fuse-ld=lld
```

Both switches are repeatable. They append to the selected project or
target-kit defaults; explicit compiler, linker, sysroot, and runtime switches
continue to take precedence over the kit.

Command-line options have the highest priority:

```sh
encore build \
  --target aarch64-unknown-linux-gnu \
  --linker clang \
  --sysroot /opt/aarch64-sysroot \
  --target-cpu cortex-a72
```

The environment fallbacks are `ENCORE_TOOLCHAIN_DRIVER`, `ENCORE_CC`,
`ENCORE_LINKER`, `ENCORE_AR`, `ENCORE_SYSROOT`, `ENCORE_TARGET_CPU`, and
`ENCORE_TARGET_FEATURES`. The current production driver flavor is `clang`;
declaring it explicitly keeps target configuration forward-compatible with
future GCC, MSVC, and vendor driver adapters without interpreting their flags
as Clang flags.

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

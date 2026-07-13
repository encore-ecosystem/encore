# Bare-Metal Cortex-M

This example links a freestanding `thumbv7em-none-eabi` ELF with a project
runtime and linker script. It uses no board-specific compiler behavior.

```sh
encore build --profile release --emit binary
llvm-objcopy -O binary target/thumbv7em-none-eabi/release/bare_metal firmware.bin
```

Replace `platform/startup.c`, `platform/memory.ld`, the CPU, and target flags
with those required by the selected microcontroller and board.

# enc_future smoke examples

This folder contains smoke examples for the self-hosted compiler flow.
Examples are mirrored from `encore/examples` and can include additional local cases.

## Layout

Each subdirectory in this folder is treated as a smoke project.

## Run one example with `enc_future`

From an example directory:

```bash
../../target/debug/encore build
```

Note:
- Current `enc_future` build mode writes a frontend payload (`.ehir`).
- Missing parent directories for payload are created automatically under `target/...`.

## Run all smoke examples

From `enc_future/examples`:

```bash
./run_smoke.sh
```

`run_smoke.sh` scans all immediate subdirectories and runs `encore build` in each.

## IR golden workflow (host compiler)

These checks use the Python host compiler (`ENCORE_HOST_BIN` or default `../.venv/bin/encore`) because `enc_future` build currently stops on frontend payload.

1. Update golden IR snapshots:

```bash
./update_ir_golden.sh
```

2. Validate generated IR against golden files:

```bash
./run_ir_golden.sh
```

Note:
- `heap` is intentionally skipped in host-based checks due a known host LLVM backend type mismatch on this example.

## Executable smoke workflow (host compiler)

Build and run executable examples, then verify exit codes:

```bash
./run_exec_smoke.sh
```

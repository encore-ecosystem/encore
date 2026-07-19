# Encore vs Rust benchmarks

This directory contains small, equivalent programs for comparing generated
Encore and Rust code. Every benchmark prints a deterministic checksum; the
runner refuses to report timings when the two implementations disagree.

The suite covers several complementary workloads:

| Benchmark | Workload |
| --- | --- |
| `arithmetic` | integer arithmetic and bit operations |
| `recursive` | recursive function calls (`fib(40)`) |
| `vector` | allocation, traversal, reads, and writes of a large vector |
| `mandelbrot` | branch-heavy floating-point fractal iteration |
| `spectral_norm` | dense numerical kernels over dynamic vectors |
| `binary_trees` | recursive graph construction, traversal, and destruction |
| `nbody` | mutable structures and floating-point particle interaction |

## Requirements

- an Encore compiler (by default `../target/extreme/encore`)
- `cargo` and `rustc`
- Python 3.9 or newer
- `clang` and `lld`, as required by Encore's `extreme` profile

## Run

From the repository root:

```sh
python3 benchmark/run.py
```

The default run performs a cold build of each program and then executes each
binary seven times. Build caches inside `benchmark/target` and each Encore
project's `target` directory are removed before measuring compilation.

Useful options:

```sh
python3 benchmark/run.py --runs 15
python3 benchmark/run.py --bench arithmetic --bench vector
python3 benchmark/run.py --skip-build
python3 benchmark/run.py --encore-bin /path/to/encore
```

Encore is compiled with `--profile extreme`. Rust uses the release profile in
`rust/Cargo.toml`: optimization level 3, thin LTO, one codegen unit, and abort
on panic. `.cargo/config.toml` enables the native host CPU, matching Encore's
host-targeted `extreme` profile. The resulting binaries are intentionally not
portable to older CPUs.

For less noisy runtime numbers, close background applications, disable CPU
power saving, and run the suite several times. These are microbenchmarks, not
a substitute for measuring a complete application.

## Adding a benchmark

1. Add `encore/<name>/encore.toml` and `encore/<name>/src/main.enq`.
2. Add the matching Rust program at `rust/src/bin/<name>.rs`.
3. Add `<name>` to `BENCHMARKS` in `run.py`.
4. Make both programs print exactly the same deterministic checksum.

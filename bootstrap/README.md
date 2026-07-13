# Native stage0

`encore-stage0-linux-x86_64.gz` is the temporary trust root for the first
fully native Encore release. CI runs it only on Linux to translate the current
compiler into target-specific LLVM IR. Each target runner then compiles that IR
with its native Clang and performs two self-hosting generations before tests and
packaging.

The binary was generated from the `feature/v0.1.3` native compiler, linked in an
Ubuntu 22.04 container, and requires glibc 2.34 or newer. Its compressed SHA-256
is recorded alongside it. Once a native release is published, this seed should
be regenerated from a pinned release artifact and its provenance updated here.

Reproduction after generating `encore.ll` for `x86_64-unknown-linux-gnu`:

```sh
clang -O3 encore.ll core/runtime.c index/ehir-llvm-backend/runtime.c \
  index/rich/runtime.c -o encore-stage0-linux-x86_64
gzip -9 encore-stage0-linux-x86_64
```

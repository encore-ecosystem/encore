# Native stage0

`encore-stage0-linux-x86_64.gz` is the temporary trust root for the first
fully native Encore release. CI runs it only on Linux to translate the current
compiler into target-specific LLVM IR. The release verification job requires a
byte-identical two-generation self-host fixed point. Each target runner then
compiles its IR with native Clang and builds the final optimized compiler before
tests and packaging.

The current binary was generated from commit
`a74c00ba5627e2939d3870fd2ef46b399a2554a7` in an Ubuntu 22.04 container and
requires glibc 2.34 or newer. Compressed and uncompressed SHA-256 files plus
compiler version, source commit, target, and build system provenance are stored
alongside it. CI verifies all metadata and executes `--version` before use.

Regenerate all stage0 files from a clean checkout and an existing native
compiler with:

```sh
scripts/update-stage0.sh index/encore/target/extreme/encore
git diff -- bootstrap
```

The update uses deterministic gzip metadata and records the checked-out commit.
Review and commit the binary, both hashes, and provenance together. Once a
native release is published, regenerate this seed from a pinned release binary
instead of a development build.

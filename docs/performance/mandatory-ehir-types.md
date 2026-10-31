# Mandatory EHIR types: preliminary Graphene measurement

`Variable.typ` is now a required `Type`. Parsing binds SSA names while constructing
instructions; it no longer rewrites instructions to recover missing types.
Preparation, the function cache and LLVM share the canonical graph, without the
previous program-wide freeze/thaw conversions. Indexed export is still optional.
The Encore frontend continues to emit and parse EHIR text.

Compared revisions: `edd4225` and `2a1454c` on
`perf/hot-compilation-0.1.12`. These are successive development compilers, not a
comparison with the published 0.1.11 release.

## Method

Native Linux, Ryzen 7 7700, 16 logical CPUs, automatic workers, dev profile,
Clang/LLD 23.1.3, no profiler or artificial CPU/memory limit. Both variants use
identical frozen Graphene and path-dependency sources and identical core SDK
sources. Each compiler retains its own target and compiled cache at the exact
paths used by its successful cold warm-up. Registry sources come from one frozen
seed. Warm-up, a unique priming edit 99 and diagnostic edit 101 are excluded.
Measured edits 100 have new source bytes; edited binaries run camera, ordinary
function and CLI probes after every build.

One pair was measured for each scenario. These observations are preliminary;
they do not establish a stable percentage improvement. Candidate ran first in
the measured session; diagnostic compiler order is reversed. Shared-host load
and warm OS caches can affect the comparison.

| Edit | Before, s | After, s | Observed time reduction |
|---|---:|---:|---:|
| No changes | 6.224 | 6.076 | 2.4% |
| Method body | 217.368 | 207.799 | 4.4% |
| Ordinary function body | 269.417 | 246.863 | 8.4% |
| Three lines before main | 241.301 | 231.271 | 4.2% |

For changed-source builds, the largest individual process RSS rose from about
6.29–6.30 GiB to 6.58 GiB, approximately 4–5%. This is not simultaneous memory
usage summed over all workers. The hot-build latency targets are still unmet.

## Remaining cost

The diagnostic method edit reused 4050 of 4211 semantic bodies and 4779 of 4780
prepared EHIR functions; 257 of 258 LLVM modules avoided emission.

| Excluded diagnostic method edit | Before, s | After, s |
|---|---:|---:|
| Prepare semantic inputs | 97.364 | 97.852 |
| Complete frontend | 156.016 | 158.126 |
| Parse EHIR (inside frontend) | 10.250 | 10.577 |
| Normalize/prepare backend | 17.523 | 18.454 |

These phases overlap and must not be summed. This check does not demonstrate an
EHIR-stage speedup: that stage was slightly slower in the diagnostic sample.
The observed end-to-end reductions above are preliminary and cannot be assigned
to one pass. The main remaining cost is preparing frontend semantic inputs,
even when most function bodies are reused. Mandatory EHIR types do not eliminate
that cost or reparsing the frontend's textual EHIR.

## Validation

55 relevant root tests, 34 EHIR package tests and 26 CLI contracts passed.
The test suite includes rejection of optional value types, unknown and
inconsistently typed SSA references, invalid prepared-cache graphs and real
native backend/library consumers. A pre-existing lost async diagnostic was also
fixed: standalone compilation reports the EHIR error before invoking a linker.

Two fresh extreme self-host generations are byte-identical:
`7bff508c3f83f25baabb021de5fd5cc05965b5618db400fff13c8e77dbb96f99`.

The final Graphene incremental executable and a build with an empty compiled
cache and target directory are byte-identical. All runtime probes passed.
Executable SHA256: `fbeedf8d0f1b9fa27ccabcfc341314f4accdf08b473b65469e1639307c160825`.

Raw report and reproducer are retained locally in
`target/strict-ehir/graphene-native-paired.json` and
`target/strict-ehir/benchmark-native.py`; detailed logs are in
`target/strict-ehir/native-paired-logs`. Initial instrumented Graphene source
SHA256 is `faf2b1e5085d839f8149a7933bee5da56bca9115eb12d8f8f74415b8f7b46e11`;
core SDK SHA256 is `f0d94d45ff870964682403cb7424f38f1f6c4e7d1f396454648715f310b8109f`.

An earlier cache-relocation attempt rechecked all 4211 semantic bodies on its
first edit. That canceled run is excluded. The general benchmark harness now
performs an excluded fresh body edit after restoring seeded caches, instead of
assuming that an archive hit also warms finer-grained contexts.

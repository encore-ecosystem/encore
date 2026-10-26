# Cold compilation: 2026-10-26

Baseline: `22a7fe225b48a2f4fe2deee0c1fd498d5eb03369`. Candidate: `perf/cold-compilation`.
Candidate code commit: `2f75532274431f8d424ac78b1165772a750dfb03`. Both compilers build the same frozen candidate sources. Compiler identities, source digest, individual samples, memory/cache measurements and verification records are in [the JSON evidence](cold-compilation-2026-10-26.json).

Cold compiler builds took 10–15% less time and applications 5–9% less. The fixed test subset stayed essentially unchanged. Peak individual process RSS increased by about 25%; both profiles remained within the 2 GiB container limit.

## Changes

- Reuse checked semantic bodies for safety inference within one package compilation.
- Index safety declarations and reverse dependencies by module, owner and function name, preserving the conservative join of every overload and immutable dependency effects.
- Reuse parsed EHIR for backend preparation and precomputed function-lowering keys for cache probes and translation.
- Return immediately for missing lowering-cache records without creating lock files or directories; existing records still undergo locked verification.
- Expose detailed package phases through `build --timings`, without a profiler.

## Measurements

AMD Ryzen 7 7700; Linux x86-64; Clang/LLD 18.1.3. Each run uses one container limited to two CPUs and 2 GiB RAM, with no swap. No profiler. Cold means empty project output and private compiled/registry caches; dependency sources are already available and OS page cache is retained. Warm runs immediately follow their cold run. Baseline and candidate run sequentially in alternating order. Applications use five pairs, compiler builds and the fixed subset use three pairs at each worker count. Program output and test selection are checked outside or alongside each measurement.

Times below are medians. Reduction is the median within-pair percentage reduction, so it can differ slightly from the ratio of the two median times. Positive means faster.

| Workload | Workers | Cache | Pairs | Baseline, s | Candidate, s | Time reduction |
|---|---:|---|---:|---:|---:|---:|
| Application with std | 1 | cold | 5 | 9.490 | 8.815 | +7.10% |
| Application with std | 1 | warm | 5 | 0.401 | 0.421 | -4.97% |
| Application with 8 dependencies | 1 | cold | 5 | 12.245 | 11.603 | +5.23% |
| Application with 8 dependencies | 1 | warm | 5 | 0.462 | 0.462 | +0.03% |
| Application with std | 2 | cold | 5 | 7.704 | 7.005 | +8.93% |
| Application with std | 2 | warm | 5 | 0.361 | 0.362 | -0.08% |
| Application with 8 dependencies | 2 | cold | 5 | 8.893 | 8.189 | +7.71% |
| Application with 8 dependencies | 2 | warm | 5 | 0.421 | 0.422 | -0.02% |
| Compiler, dev | 1 | cold | 3 | 296.754 | 255.809 | +13.75% |
| Compiler, dev | 1 | warm | 3 | 1.707 | 1.705 | +0.08% |
| Compiler, dev | 2 | cold | 3 | 275.390 | 234.444 | +14.97% |
| Compiler, dev | 2 | warm | 3 | 1.589 | 1.605 | -0.35% |
| Compiler, extreme | 1 | cold | 3 | 385.227 | 345.302 | +10.36% |
| Compiler, extreme | 1 | warm | 3 | 1.747 | 1.746 | +0.02% |
| Compiler, extreme | 2 | cold | 3 | 323.764 | 282.805 | +12.93% |
| Compiler, extreme | 2 | warm | 3 | 1.666 | 1.645 | +1.28% |
| Fixed 8-test subset | 1 | cold | 3 | 78.480 | 78.112 | -0.07% |
| Fixed 8-test subset | 1 | warm | 3 | 7.843 | 7.888 | -0.26% |
| Fixed 8-test subset | 2 | cold | 3 | 41.484 | 41.540 | +0.45% |
| Fixed 8-test subset | 2 | warm | 3 | 5.147 | 5.135 | +0.36% |

## Memory and disk

Largest individual process RSS for cold compiler builds (median of the paired samples):

| Profile | Workers | Baseline RSS, MiB | Candidate RSS, MiB | Change |
|---|---:|---:|---:|---:|
| dev | 1 | 863.2 | 1079.6 | +25.1% |
| dev | 2 | 858.1 | 1074.5 | +25.2% |
| extreme | 1 | 863.5 | 1075.8 | +24.6% |
| extreme | 2 | 859.2 | 1075.4 | +25.2% |

Compiler builds have a memory tradeoff: median maximum process RSS increased by about 25% in both profiles and at both worker counts. All runs remained confined to the 2 GiB hard memory limit with swap disabled. This is not a memory-reduction claim. Cache and output allocation are recorded for every sample in the JSON.

Peak RSS in the JSON is the largest individual process, not aggregate simultaneous worker memory. These are local measurements under the stated limits, not GitHub runner timings. Warm application builds take about 0.4 s; the std application with one worker varies by about 20 ms, near the sampling interval. The complete test-suite run is correctness validation, with shared private caches between validation gates; its elapsed time is not a paired performance claim.

Standalone test compilation follows `compile_test_ast` / `compile_entry_ast_in` in `src/modes/build.enq`. It has a separate lowering/codegen path from the package workers optimized here, so the fixed subset serves as a latency regression check for this iteration. Its measured results are listed separately from package builds.

## Validation

LSP completion tests use a private `ENCORE_HOME` whose library index points to the frozen package sources. An initial completion failure without an installed library index was resolved by this environment setup; no compiler change was needed.

All 601 compiler tests, tests for 10 system libraries, nine benchmark-script contracts, project metadata/constants, cache lifecycle, live terminal progress, reflection, native codec/string/runtime checks, source check/lint/format, LSP build and its 12 test scripts, and examples passed. Existing lint warnings remain.

The published compiler built stage 1, which built stage 2, which built stage 3, with independent compiled caches. All three binaries are byte-identical:

`92d5c66a553ef4619a9b240cbd6dd1be6222c0b120747815103a9cf138638b3b`

Windows GNU x86-64 and ARM64 applications linked against the available target kits. The x86-64 executable ran successfully under Wine before and after a manifest-version edit, exercising project constants, dependency generics and async nominal layouts. Full macOS, Linux ARM64 and Windows MSVC validation was not available locally.

## Reproduce

Build the baseline from the commit above and the candidate from this branch, using the same published seed, native tools, profile and resource limits. Then run the benchmark helper inside that same bounded environment:

```sh
python3 scripts/benchmark-compiler-tests.py /path/to/candidate \
  --baseline-compiler /path/to/baseline --source "$PWD" \
  --scenario projects --profile dev --jobs 1,2 --repetitions 5 --warm \
  --output target/performance/projects.json
```

Repeat with `--scenario build --profile dev`, `--scenario build --profile extreme`, and `--scenario subset`, each using `--repetitions 3` and a distinct output file. The profile option controls build scenarios; the subset invokes `encore test` with its normal compilation settings. Each report retains raw logs and frozen source archives beside the JSON. The fixed subset is a latency sample, not a substitute for the complete compiler suite.

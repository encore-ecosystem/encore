# Cold compilation after native plugins: 2026-10-28

Baseline: `aa2ed6f609bd6b3cb31bea925be1c3dce5d4d4af` (the squash of PR #176). Candidate: this PR's compiler sources. Both compilers build the same frozen candidate input; hashes, raw paired samples, cache/disk data and validation are in [the JSON evidence](cold-compilation-2026-10-28.json).

This report measures the combined semantic/safety/EHIR and nominal-resolution optimizations on the current source tree. The [2026-10-26 report](cold-compilation-2026-10-26.md) records the earlier iteration against its original baseline.

## Changes

- Reuse checked semantic bodies within package safety inference and index effect lookup while retaining all overloads and immutable dependency effects.
- Reuse parsed EHIR and precomputed function keys. Missing lowering entries do not create lock directories or files.
- Admit possible nominal identifiers with one scan per module, retaining the existing scoped rewrite and sequential replacement behavior. Unknown/non-word candidates and allocation failure remain conservative.
- Cache qualified type spellings per translation context, including lexical module and generic binder. Bound admission to 4,096 entries with 1,024-byte keys and 2,048-byte values; filtered scopes and oversized inputs use the original resolver.
- Copy type-string fragments instead of concatenating individual characters. Expose package phase timings without a profiler.

## Measurements

AMD Ryzen 7 7700, Linux x86_64, Clang/LLD 18.1.3. One container at a time, two CPUs/workers, 2 GiB RAM and swap disabled. Three alternating sequential pairs per workload; warm immediately follows cold. Cold samples use empty output and private compiled/registry caches. Dependency downloads are excluded; OS page cache remains warm. Diagnostic frontend profiling is disabled. These are local results, not GitHub runner timings.

Times are medians. Reduction is the median percentage reduction within matching pairs, so it can differ from the ratio of the two displayed medians. Positive means faster.

| Workload | Cache | Pairs | Baseline, s | Candidate, s | Time reduction |
|---|---|---:|---:|---:|---:|
| compiler-dev/build | cold | 3 | 295.447 | 179.638 | +39.34% |
| compiler-dev/build | warm | 3 | 1.627 | 1.627 | +0.01% |
| subset/subset | cold | 3 | 42.784 | 42.745 | +0.09% |
| subset/subset | warm | 3 | 4.819 | 4.819 | +0.43% |
| projects/app-std | cold | 3 | 9.034 | 7.611 | +15.79% |
| projects/app-std | warm | 3 | 0.382 | 0.381 | +0.04% |
| projects/eight-deps | cold | 3 | 9.919 | 8.533 | +13.99% |
| projects/eight-deps | warm | 3 | 0.422 | 0.442 | -4.68% |

## Memory and disk

RSS is the largest individual process, not aggregate simultaneous worker memory. Each complete run is constrained by the same 2 GiB container limit. Cache allocation measures disk blocks, not only logical file length.

| Cold workload | Baseline RSS, MiB | Candidate RSS, MiB | RSS change | Baseline cache, MiB | Candidate cache, MiB |
|---|---:|---:|---:|---:|---:|
| compiler-dev/build | 903.1 | 1115.7 | +23.5% | 80.4 | 80.4 |
| subset/subset | 640.5 | 642.1 | +0.2% | 0.0 | 0.0 |
| projects/app-std | 103.1 | 103.6 | +0.5% | 4.7 | 4.7 |
| projects/eight-deps | 103.4 | 103.2 | -0.2% | 5.5 | 5.5 |

The package worker retains checked semantic facts for reuse; this has a memory tradeoff. Interpret the speed and RSS results together. Warm builds and the fixed subset are separate latency checks. Warm project builds take about 0.4 s; their 20 ms differences are close to the measurement polling interval, so small percentage changes are not a precise regression estimate. The subset contains eight language/lexer/parser/translator/cache programs and does not replace the full compiler suite.

## Validation

- 43 focused compiler tests passed: translator oracles, safety/effect parity, function-cache replay, lowering-cache storage, incremental cache/timings, all nine issue regressions, plugin contracts, and related namespace/metadata cases.
- All 33 native/typed plugin checks, cache lifecycle, project constants, source check and selected-file lint passed. Formatting and nine benchmark-script contracts passed. Existing lint warnings remain.
- The native identity test passed with strict C warnings on Linux and Windows GNU x86_64 under Wine. Native non-Linux compiler execution and the complete suite are delegated to the PR CI matrix and are not part of this local run.
- Two successive `extreme` self-hosted compilers are byte-identical:

`3618c4a39be41e0607b7aa3d2062869ec7be4d1e25aabf3642441670a18497d0`

The measured compiler sources match the final code digest in the JSON. Documentation/report files added afterward do not change those compiler sources.

## Reproduce

Build the baseline and candidate with the same native toolchain. In the same bounded environment, run:

```sh
python3 scripts/benchmark-compiler-tests.py /path/to/candidate \
  --baseline-compiler /path/to/baseline --source "$PWD" \
  --scenario build --profile dev --jobs 2 --repetitions 3 --warm \
  --output target/performance/compiler-dev.json
```

Repeat with `--scenario subset` and `--scenario projects`, choosing distinct output files. The subset uses normal test compilation settings. Raw reports retain logs and frozen source archives next to the output JSON.

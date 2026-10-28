# Development and Performance

Start with a correct, testable program. Measure before choosing a more complex
representation or introducing concurrency.

## A short feedback loop

Run `encore format --check`, `encore check`, and a focused `encore test --filter`
while changing a function. Run the relevant complete package tests before
shipping. `check` does not replace a native build: linking, runtime behavior,
and platform dependencies need executable verification.

Keep `encore.toml` and `encore.lock` together. Use `sync` to restore dependencies
and `update` only when selecting newer ones intentionally. Development `path@`
references do not make a published package portable: consumers need published
dependencies. See [packages](packages.md) and [publishing](publishing-packages.md).

## Measure the right thing

Separate cold compilation, warm incremental compilation, application startup,
and steady-state execution. Comparing a cached build with a clean build says
nothing about the optimizer's speed. Record the compiler release, target,
profile, input size, repetitions, elapsed time, and memory when relevant.

Compiler contributors can compare complete builds and the CI test suite across
worker counts without enabling a profiler:

```sh
python3 scripts/benchmark-compiler-tests.py /path/to/candidate-encore \
  --baseline-compiler /path/to/released-encore \
  --baseline-ref v0.1.6-neumann --scenario all \
  --jobs 1,2,4,8,16,auto --repetitions 3 --warm \
  --output target/performance/results.json
```

The default build profile is `extreme`; `--profile` also accepts `dev` and
`release`. `--scenario build` measures compiler builds, `suite` runs the complete
compiler CI test fixture, and `standalone` retains the four small language,
lexer, parser, and translator programs for latency comparisons. One selected
test offers little parallel work, so use `suite` to assess test throughput.

Use `--scenario projects --profile dev` for a small executable using `std` and
an executable with eight independent dependencies. Both execute the built
program and verify its result outside the measured interval. `--scenario subset`
runs the fixed eight lexer, parser, translator and cache regression programs;
it is a latency sample, not a substitute for the complete suite. Pair five
project repetitions and three compiler-build repetitions at `--jobs 1,2`
when working within a two-CPU memory-limited container.

`build --timings` adds package phase details for dependency metadata, workspace
loading, semantic checks, safety inference, lowering context/cache/translation, EHIR parsing,
frontend checkpoint publication, backend normalization and ready-record
publication. These fields supplement the existing timings and do not require
a profiler. Concurrent phase durations are not an additive wall-time breakdown.
Package workers reuse their checked body facts during safety inference; this
reuse stays inside the same compilation and does not create another disk cache.

Nominal type resolution also keeps a translation-local cache, limited to 4,096
entries, 1,024-byte keys and 2,048-byte values. Generic shadowing scopes and
oversized types use the ordinary resolver. An identifier index scans each EHIR
module once to reject impossible nominal rewrites; the scoped rewriter still
handles binders, members, strings and comments. Replacements update the index
so later names retain the same sequential rewrite behavior. These indices are
released with the translation context and add no persistent cache format.

Every cold sample has an independent frozen source tree, private Git metadata,
empty project output, and private compiled-package/registry caches. A warm
sample immediately follows it with those same caches. Source copying and
baseline downloads are outside the timed interval; native toolchains and OS
filesystem buffers are retained. User caches are never cleared. Requests above
the online CPU count are coalesced (matching current compiler discovery); `auto` exercises the compiler's actual
default without an explicit `--jobs` argument. Baseline and candidate execute
sequentially on the same machine, alternating their order between repetitions.

The JSON report and adjacent Markdown table contain medians, minimum/maximum,
standard deviations, speedups, CPU time and CPU-equivalent utilization where
supported, compiler hashes, source digests, and machine/CPU/memory limits.
`max_process_rss_kib` is the largest individual process RSS reported by `wait4`,
not the simultaneous memory of all workers. Missing platform metrics remain
null. Raw logs and native test reports are retained next to the result; timed
out or failing invocations are failures, not successful timing samples. Test
IDs must be unique and match across worker counts and cold/warm repetitions
for each compiler/source variant.

After an interruption, add `--resume` to the same command. Completed cold/warm
pairs are retained; an incomplete pair restarts with empty caches. Resuming
requires identical compiler hashes, source snapshots, benchmark code, machine
and toolchain settings. The report marks completion explicitly and preserves
the interrupted pair's logs. Stop the original process before resuming.
Native Windows uses Git Bash beside Git; `--bash` selects an explicit executable.

Test JSON reports retain `summary.duration_ms` as the sum of test durations.
`summary.wall_duration_ms` records elapsed suite time,
`summary.harness_duration_ms` records shared harness preparation, and
`summary.jobs` records the resolved worker limit. Parallel summed durations can
exceed elapsed time. Test workers take the next heaviest available job from a
shared queue, while each test still runs in its own process and final report
order remains stable.

To collect paired native CI measurements, dispatch Native CI with
`performance_baseline_tag=v0.1.6-neumann` and `performance_jobs=auto` (or an
explicit comma-separated matrix). Each target verifies the published baseline
archive and adoption provenance before running both compilers on one runner.
The three CI repetitions run in separate jobs to stay within GitHub's six-hour
job limit. Each baseline/candidate pair shares one runner, and the aggregate
reports the median of within-runner speedup ratios. It retains each repetition's
environment and elapsed-time distribution, and requires all three complete
pairs with matching compiler/source identities and selected tests.
Performance jobs are opt-in and do not impose a single-test time threshold.

Use `release` for a portable optimization baseline; use `extreme` when its
native toolchain requirements and CPU tuning are appropriate. Do not distribute
a host-tuned binary to unknown CPUs without configuring a suitable baseline.
See [Getting Started](getting-started.md) for profiles and [targets](targets.md)
for the host/target distinction.

For runtime timings use the monotonic `std::time::perf_counter_ns` or
`perf_counter_ms`, not wall-clock calendar time. Avoid printing inside the hot
loop. Warm up separately, repeat measurements, and verify the output so an
incorrect or optimized-away computation does not look like an improvement.

## Understand the cost model

Generic specialization trades potential code growth for concrete dispatch.
`dyn Trait` introduces runtime dispatch. Copying an inline payload copies its
fields; copying a node handle shares storage and participates in ownership.
Cloning a collection allocates independent storage. Repeated string concatenation
can allocate repeatedly. Native threads have startup and join overhead; dividing
tiny tasks into many threads can be slower than a sequential loop.

These are reasons to measure, not universal claims that one construct is slow.
The [parallel project](parallel-project.md) checks correctness before speed.

## Caches and debugging

Registry caches hold downloaded dependencies; build caches hold compilation
work; LSP caches hold analysis metadata. They solve different problems. Do not
delete all three as the first response to an unresolved import. First check
the manifest, lockfile, selected compiler, and the failing command's output.

When reporting a cache regression, compare the same source and compiler with
a warm build and a clean **project-local** build directory, preserving logs.
Do not remove a global installation or registry just to force a rebuild.

**Exercise:** a warm compile takes less time after adding a worker. Is that
evidence that runtime parallelism improved?

<details><summary>Answer</summary>

No. Compilation and execution are different measurements, and the cache state
changed. Time the same verified executable workload with the same inputs.

</details>

# Graphene incremental compilation protocol

This workload measures the dev edit/build loop on a frozen Graphene checkout,
including dirty working-tree inputs and its local path dependencies. It changes
the workload copies only. The compiler source checkout and the developer's
Graphene checkout are never rewritten by the benchmark.

Each compiler has a private persistent build cache, registry, SDK snapshot,
workspace and target directory. Copy all installed registry metadata and package
versions, including versions selected by path dependencies' lock files. No
dependency download belongs in the measured interval. Run on the native host
with automatic workers and no artificial CPU or memory limits.

After an excluded initial warm-up, run five paired sessions, reversing compiler
order between sessions. Each session applies these edits cumulatively:

| Case | Edit | Runtime check |
|---|---|---|
| unchanged | Build the previous state again | Previous camera result and CLI message |
| method-body | Change the camera's yaw coefficient | Headless camera probe returns the new value |
| function-body | Change the ordinary camera speed helper body | Headless function probe returns the new speed |
| main-body | Change the cook usage message inside the large main function | CLI prints the new message |
| relocate | Insert three lines before main | Both probes still return their expected results |
| interface | Rename the camera method and update its callers | Both probes still pass |
| css | Append an unused stylesheet rule | Control: compiler inputs should remain cached |

Edits use new revision IDs in every session. Reverting to an already cached
source state is not an incremental-compilation measurement. Compilation success
alone is insufficient: executing the resulting binary detects stale output.
Tests for the harness explicitly exercise and reject such stale binaries.

Timed samples do not enable frontend profiling or `--timings`. One additional
diagnostic session records package, semantic, lowering, object reuse and cache
restore phases; exclude it and warm-up from headline results. Keep raw logs and
the frozen inputs alongside the report. Report medians and median percentage
reductions within matching pairs, with all five paired observations. Check that
the unchanged-build median does not regress by more than 5%.

The RSS metric is the largest individual process reported by `wait4`, not the
simultaneous sum of worker memory. Disk measurements include both logical bytes
and allocated blocks, outside timed intervals. OS page cache remains warm.

```sh
python3 scripts/benchmark-compiler-tests.py /path/to/candidate \
  --source "$PWD" --baseline-compiler /path/to/encore-0.1.11 \
  --baseline-ref v0.1.11-neumann --scenario incremental \
  --project-root /path/to/Graphene --registry-seed /path/to/frozen-registry \
  --profile dev --jobs auto --repetitions 5 --verify-clean \
  --output target/performance/graphene-incremental.json
```

For a focused iteration, select scenarios with
`--incremental-cases unchanged,method-body,function-body,relocate`. The report
records the selected cases; omitted scenarios have no measured result.

Already prepared caches can be copied with
`--baseline-cache-seed /path/to/cache` and `--candidate-cache-seed /path/to/cache`.
This saves excluded cold warm-ups.
Use `--first-repetition` to choose edit IDs absent from that seed's history;
the seed digest is recorded in the report. The default uses empty private
caches. Resume is deliberately unsupported: interrupted sessions require a new
output path and fresh edit IDs.

`--verify-clean` saves the incremental output, rebuilds the candidate with an
empty cache and target directory, executes all probes, and requires the final
executable to be byte-identical. This extra build is excluded from the medians.

Before interpreting performance, run the relevant type-scope, safety,
function/closure replay, package-cache corruption, namespace and concurrency
contracts. Compare incremental and clean executables and verify two successive
extreme compiler builds are byte-identical. At least the last build must use an
empty build cache so that a cached compiler executable cannot masquerade as
bootstrap convergence.

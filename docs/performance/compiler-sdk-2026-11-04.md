# Compiler and synchronization SDK validation

The local candidate implements the compiler fixes and runtime SDK work tracked in
#180–#195, together with the generic context, unit storage and frozen method return
regressions #196–#198. No release or global installation is produced by this work.

The [machine-readable evidence](compiler-sdk-2026-11-04.json) records executable
hashes, source identities, profile, host, worker selection and full phase reports.
The candidate compiler uses the **dev** profile, built with ordinary
`encore build` and automatic workers. The run benchmark used a 4 GiB memory limit
and 3 GiB swap allowance; compiler self-builds used 5 GiB and 3 GiB respectively.

## Unchanged run preparation

The workload is a frozen Zodiac checkout and a frozen sibling Luma checkout.
Their source fingerprint was checked again after execution. `encore run -- --help`
executes the real Zodiac binary without opening another desktop window. The hello
workload prints one line and depends on the checkout's `std`.

Each workload has one cold invocation followed by ten unchanged invocations.
Nearest-rank p95 for ten warm observations is their maximum. Whole-command wall
latency includes the small help/hello program; `time_to_exec_ms` excludes it.

| Workload | Warm wall median | Warm wall p95 | Launch preparation p95 | Cold wall sample |
| --- | ---: | ---: | ---: | ---: |
| Zodiac | 937 ms | 949 ms | 943 ms | 145.963 s |
| Hello with std | 222 ms | 225 ms | 218 ms | 11.568 s |

All warm invocations report an input-receipt hit. Cold compilation and warm
launch preparation remain separate measurements. These measurements meet the
local warm targets of 1 second for Zodiac and 250 ms for hello. They do not claim
a cold-build speedup from the user's earlier 5–6 second startup observation.

## Generated SDK invalidation matrix

`scripts/benchmark-sdk-builds.py` generates 463 endpoint functions and response
structures, executes every resulting binary, and records cold, warm, application
body, dependency body, public interface, reachable generic, unreachable generic
and native flag edits. Each repetition owns a new private project and package
cache. The default runner supports three repetitions; this validation records
one smoke repetition for each compiler.

| Case | Published 0.1.12 | Local dev candidate |
| --- | ---: | ---: |
| Cold | 6.887 s | 9.771 s |
| Warm | 0.545 s | 0.143 s |
| Application body | 1.699 s | 1.381 s |
| Dependency body | 2.391 s | 2.933 s |
| Public interface | 4.608 s | 7.092 s |
| Reachable generic | 4.353 s | 8.217 s |
| Unreachable generic | 3.229 s | 8.804 s |
| Native flags | 2.414 s | 3.900 s |

The baseline is the checksummed published native 0.1.12 compiler, whose tagged CI
builds with `extreme`. The local compiler is `dev`. Other validation processes
were active. These samples prove the fixture and record observed costs; different
compiler optimization profiles and a single repetition do not support an overall
performance comparison. The slower cold/edit samples are retained explicitly.
Use the same compiler profiles and repeated, otherwise idle runs for that claim.

## Correctness evidence

- Full core, platform, std and LLVM-backend suites: 11, 2, 36 and 18 tests passed.
- Eight native ownership/concurrency probes passed AddressSanitizer and
  ThreadSanitizer, including 100,000 cancellation ancestors and concurrent watch
  publishers, closure, wakeup and final-drop behavior.
- Local HTTP integration verified binary/chunked responses, cancellation,
  executor handoff, active-request abandonment, and restoration of native/core
  object, thread and descriptor counts.
- Thirteen compiler CLI contracts passed, including imported package identity,
  missing argument rejection, authored plugin formatting, standalone plugin ABI
  parity, generated helper cache replay, build-script/header invalidation,
  consumer registry selection, and incremental/corrupt cache restoration.
- Unit aggregate storage, generic `with`, receiver ownership, guard thread/await
  restrictions, frozen mutation and opaque JSON construction have executable
  regressions. Cached callback lowering matches a fresh translation.

Timing reports are assembled in a private build workspace and atomically
published under a short profile lock. `command_id` identifies the producing
process; a run invocation only attaches launch timing to its own report. This
avoids checksum races and mixed reports during concurrent builds.

The cache lifecycle probe also recovers from a deliberately interrupted build
and two concurrent builds of one project. With 500 disposable entries and a zero
cache budget it resumed collection over 85 commands, retained an exclusively
locked entry and an external symlink, and reclaimed the entry after its lock was
released. The maximum forced-maintenance warm command was 235 ms. The cooperative
budget is per slice; one invocation need not complete an inventory or eviction.

Two consecutive local dev self-builds produced the same SHA-256:
`63a7ae55ba0f5f964aae7e5ac4a8d74f15777f4d7727a3523fbe371e7ca8ee22`.
The final build missed both the input receipt and final link cache; it rebuilt
the compiler and linked its output. Package caches were shared. Native CI retains
its separate, isolated-cache `extreme` stage convergence check; that remote result
is not claimed by this local report.

The default full-project lint did not finish the large translator's `unused-mut`
analysis after 49 minutes with the dev compiler or 14 minutes with published
0.1.12, and was stopped. These runs emitted warnings without an observed error;
they are incomplete. `lint --allow unused-mut` completed with warnings and exit 0.
No repository lint configuration was weakened. Changed Encore declarations were
formatted and whitespace validation passed; whole-file formatting of the largest
existing compiler modules was avoided after its similarly prolonged traversal.

The existing cache-policy CLI suite passed all 12 checks, including read-only dry
runs, corruption/allocation-failure handling, locked entries, symlinks and retained
workspaces. Its isolated SHA-failure native probe supplies the new filesystem SHA
and real monotonic-clock ABI dependencies. Existing terminal-progress integration
also passed native frames/resize/lifecycle, redirected CLI output, parallel test
events and user-program terminal handoff.

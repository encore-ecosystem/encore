# Compiler SDK submodules

Encore pins 17 public package repositories in `.gitmodules`. The superproject's
Git tree records the commit to use for each path. Builds never select a branch
head or run `git submodule update --remote`.

| SDK directory | Repository in encore-language-index |
| --- | --- |
| core | core |
| platform | platform |
| std | std |
| rich | rich |
| serialize | serialize |
| json | json |
| binary | binary |
| log | log |
| profile | profile |
| ehir-core | ehir_core |
| ehir | ehirlib |
| ehir-llvm-backend | ehir_llvm_backend |
| toml | toml |
| colorterm | colorterm |
| llvm | llvm |
| argparse | argparse |
| secret-store | secret_store |

These are the compiler's existing SDK packages. The independent `logger` and
`profiler` packages retain their existing APIs and repositories.

## Checkout and package changes

```sh
git clone --recurse-submodules --branch trunk https://github.com/encore-ecosystem/encore.git
cd encore
# Restore the package commits selected by the current compiler commit.
git submodule update --init --recursive
python3 scripts/sdk_packages.py manifest --verify-checkout
```

A submodule normally has a detached HEAD. Create a branch inside the package
before editing, commit and push its changes there, then stage the package path
in an Encore integration PR. The package commit must be available on its public
remote before the compiler PR is checked. If a package PR is squashed or rebased,
update its gitlink and rerun integration checks for the resulting SHA.

Sibling `path@` dependencies preserve the SDK's directory layout. The existing
publisher stages these as exact `index@name@version` dependencies in package
archives. Package source commits and registry publications are separate: an
existing published version cannot be overwritten with different archive bytes.

## Source snapshots and release contents

`python3 scripts/sdk_packages.py export --destination target/source-snapshot`
exports the superproject and recursively expands every gitlink at its recorded
commit. `--ref <tag>` also supports older releases with embedded SDK directories.
Submodules must already be initialized and contain the requested objects. A
missing commit produces an explicit recovery command.

Bootstrap overlays and release packaging use this exporter. Benchmark snapshots
also walk submodules; working-tree measurements preserve edited and untracked
source inputs while excluding Git metadata and ignored build outputs.

Native distributions contain all 17 packages as ordinary directories under
`lib/encore/index`, including headers, native runtimes, build scripts and tests.
They also include `SDK.json`, containing each package's repository, directory,
manifest identity and commit. Git metadata and build caches are excluded.

CI tests the extracted compiler and bundled SDK outside the source checkout with
empty build/registry caches and an unreachable registry. Both cold and warm
application builds must succeed. The application's std/json dependencies point
to the extracted SDK; core and platform are discovered from that installation.

## Verification and release order

All native bootstrap stages use one pinned SDK set. Stage2 and stage3 must be
byte-identical on each of the six target platforms. Provenance records the SDK
package list and SHA-256 of canonical `SDK.json`; restored stage3 contexts and
release promotion verify both against the checked-out gitlinks. Target-kit
metadata binds the same SDK digest and platform commit.

The preparatory migration keeps source syntax supported by Encore 0.1.14.
Release 0.1.15 can then introduce the language bridge for defaults, named calls,
conversions and both operator contracts. Release 0.1.16 adopts two-argument
operator traits and requires a published seed of at least 0.1.15. Those changes
update package commits and their compiler gitlinks together.

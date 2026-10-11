#!/usr/bin/env python3
"""Three-run medians for an executable with eight independent dependencies.

Each repetition has fresh project output and a private package cache. Legacy
compilers do not support that cache override: their system-wide caches remain
untouched. The report explicitly records this asymmetry rather than deleting
user caches or calling a hydrated legacy build an empty-cache build.
"""

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("compiler", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    repository = Path(__file__).resolve().parents[1]
    samples = {name: [] for name in ("fresh", "warm", "body_edit", "interface_edit")}
    with tempfile.TemporaryDirectory(prefix="encore-build-benchmark-") as directory:
        scratch = Path(directory)
        for repetition in range(3):
            root = scratch / str(repetition)
            (root / "src").mkdir(parents=True)
            imports, calls, dependencies = [], [], []
            for index in range(8):
                package = root / f"dep-{index}"
                (package / "src").mkdir(parents=True)
                (package / "encore.toml").write_text(
                    f'[project]\nname="bench_dep_{index}"\nversion="0.0.0"\ndependencies=[]\n')
                (package / "src/lib.enq").write_text(f'pub fn value_{index}() -> u32 {{ ret {index + 1} }}\n')
                dependencies.append(f"path@dep-{index}")
                imports.append(f"import bench_dep_{index}::value_{index}")
                calls.append(f"value_{index}() as u64")
            (root / "encore.toml").write_text(
                '[project]\nname="build_benchmark"\nversion="0.0.0"\ndependencies=' + json.dumps(dependencies) + '\n')
            (root / "src/main.enq").write_text('\n'.join(imports) + '\nfn main() -> u32 { let total = ' +
                ' + '.join(calls) + '\nret if total == 36_u64 { 0 } else { 1 } }\n')
            environment = {**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core"),
                           "ENCORE_BUILD_CACHE": str(root / "cache")}

            def measure(name):
                started = time.monotonic()
                result = subprocess.run([str(compiler), "build", "--jobs", str(args.jobs)], cwd=root,
                                        env=environment, capture_output=True, text=True, timeout=600)
                elapsed = time.monotonic() - started
                assert result.returncode == 0, result.stdout + result.stderr
                binary = root / "target/dev" / ("build_benchmark.exe" if os.name == "nt" else "build_benchmark")
                subprocess.run([str(binary)], check=True, timeout=10)
                samples[name].append(elapsed)
                print(f"run={repetition + 1} {name}: {elapsed:.3f}s", flush=True)

            measure("fresh")
            measure("warm")
            source = root / "dep-0/src/lib.enq"
            source.write_text('pub fn value_0() -> u32 { let previous = 0 ret previous + 1 }\n')
            measure("body_edit")
            source.write_text('pub fn value_0() -> u64 { ret 1 }\n')
            measure("interface_edit")
    report = {"compiler": str(compiler), "jobs": args.jobs, "repetitions": 3,
              "cache_policy": "fresh project/private package cache; legacy system cache retained",
              "samples_seconds": samples,
              "median_seconds": {name: statistics.median(values) for name, values in samples.items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["median_seconds"], indent=2))


if __name__ == "__main__":
    main()

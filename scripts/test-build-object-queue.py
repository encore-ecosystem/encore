#!/usr/bin/env python3
"""Exercise native/object scheduling through real builds of eight dependencies."""

import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def main():
    compiler = Path(sys.argv[1]).resolve()
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-object-queue-") as directory:
        scratch = Path(directory)
        root = scratch / "project with spaces"
        (root / "src").mkdir(parents=True)
        dependencies = ["path@" + (repository.parent / "encore-index/packages/std").as_posix()]
        imports, calls = [], []
        for index in range(8):
            package = root / f"dependency-{index}"
            (package / "src").mkdir(parents=True)
            (package / "encore.toml").write_text(
                f'[project]\nname="queue_dep_{index}"\nversion="0.0.0"\ndependencies=[]\n', encoding="utf-8")
            (package / "src/lib.enq").write_text(
                f'pub fn value() -> u32 {{ ret {index + 1} }}\n'
                'pub fn offset(value: u16) -> u32 { ret value as u32 }\n'
                'pub fn identity[T](value: T) -> T { ret value }\n', encoding="utf-8")
            dependencies.append(f"path@dependency-{index}")
            imports.append(f"import queue_dep_{index}::value as value_{index}")
            calls.append(f"value_{index}()")
        refs = ",".join('"' + item + '"' for item in dependencies)
        (root / "encore.toml").write_text(
            '[project]\nname="queue_probe"\nversion="0.0.0"\ndependencies=[' + refs + ']\n', encoding="utf-8")
        (root / "src/main.enq").write_text(
            '\n'.join(imports) + '\nimport std::io::println\nimport std::thread::JoinHandle\n'
            'import queue_dep_0::{offset as shifted, identity as echoed}\n'
            'fn work() -> u32 { ret 7 }\nfn main() -> u32 {\n'
            '    let handle = spawn work()\n    if handle.join() != 7 { ret 3 }\n'
            '    if shifted(5000) != 5000_u32 || echoed(1_u32) != 1_u32 { ret 2 }\n'
            '    let total = ' + ' + '.join(calls) + '\n'
            '    println(f"sum={total}")\n'
            '    ret if total == 36 { 0_u32 } else { 1_u32 }\n}\n', encoding="utf-8")
        runtime = root / "runtime.c"
        valid_runtime = 'int queue_fixture_marker(void) { return 1; }\n'
        runtime.write_text(valid_runtime, encoding="utf-8")
        environment = {**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")}
        timings = []

        def build(jobs, success=True):
            started = time.monotonic()
            result = subprocess.run([str(compiler), "build", "--jobs", str(jobs)], cwd=root,
                                    env={**environment, "ENCORE_BUILD_CACHE": str(scratch / f"cache-{jobs}")},
                                    capture_output=True, text=True, timeout=240)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return time.monotonic() - started

        def run_binary():
            binary = root / "target/dev" / ("queue_probe.exe" if os.name == "nt" else "queue_probe")
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            assert result.returncode == 0 and result.stdout.strip() == "sum=36", result
            return binary

        for jobs in (1, 2, 4, 8):
            elapsed = build(jobs)
            binary = run_binary()
            before = binary.stat().st_mtime_ns
            cached = build(jobs)
            assert binary.stat().st_mtime_ns == before, "no-op build changed its output"
            report = json.loads((root / "target/dev/encore-timings.json").read_text())
            assert report["link_cache_hit"] and len(report["units"]) == 12, report
            assert all(unit["cache_hit"] for unit in report["units"]), report
            timings.append((jobs, elapsed, cached))
            if jobs != 8:
                shutil.move(str(root / "target"), str(scratch / f"objects-jobs-{jobs}"))

        # A real Clang failure must preserve the last successfully published
        # executable. Its old receipt cannot match the changed native inputs.
        before_failure = hashlib.sha256(binary.read_bytes()).hexdigest()
        runtime.write_text('this is deliberately invalid C!\n', encoding="utf-8")
        build(4, success=False)
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == before_failure
        runtime.write_text(valid_runtime, encoding="utf-8")
        build(4)
        run_binary()
        for jobs, elapsed, cached in timings:
            print(f"jobs={jobs}: empty package cache {elapsed:.2f}s, no-op {cached:.2f}s")
    print("package/object queue: eight dependencies, cross-package spawn/join, jobs=1/2/4/8, no-op, native failure/recovery passed")


if __name__ == "__main__":
    main()

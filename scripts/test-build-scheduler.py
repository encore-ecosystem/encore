#!/usr/bin/env python3
"""Compile the actual internal scheduler/resolver modules and run their contracts."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    repository = Path(__file__).resolve().parents[1]
    compiler = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="encore-build-scheduler-") as directory:
        root = Path(directory) / "fixture with spaces"
        shutil.copytree(repository / "src", root / "src")
        # Compiler CLI modules intentionally are not exported by src/lib.enq.
        # A disposable library exposes only the modules under test. Copying the
        # sources preserves their private tests without expanding the public
        # compiler API or duplicating the implementation in a test fixture.
        (root / "src/lib.enq").write_text(
            'pub import refrain::modes::build_scheduler\n'
            'pub import refrain::project::workspace\n', encoding="utf-8")
        manifest = (repository / "encore.toml").read_text(encoding="utf-8")

        def resolve_path(match):
            value = (repository / match.group(1)).resolve().as_posix()
            return '"path@' + value + '"'

        manifest = re.sub(r'"path@([^"\n]+)"', resolve_path, manifest)
        (root / "encore.toml").write_text(manifest, encoding="utf-8")
        source = (repository / "runtime.c").as_posix().replace('"', '\\"')
        (root / "runtime.c").write_text(f'#include "{source}"\n', encoding="utf-8")
        environment = {**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")}

        def run(*arguments):
            result = subprocess.run([str(compiler), "test", "--filter", "scheduler_", *arguments],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                log = root / "target/tests/__encore_unit_harness.output.txt"
                details = log.read_text(encoding="utf-8") if log.exists() else ""
                raise AssertionError(result.stdout + result.stderr + "\n" + details)
            return result.stdout + result.stderr

        listed = json.loads(run("--list", "--format", "json"))
        assert len(listed) == 10, f"expected ten real scheduler/graph tests, got {listed}"
        print(run("--jobs", "2", "--report", "report.json"), end="", flush=True)
        report = json.loads((root / "report.json").read_text(encoding="utf-8"))
        assert report["summary"]["passed"] == 10 and report["summary"]["failed"] == 0, report
        binary = root / "target/tests/bin" / ("__encore_unit_harness.exe" if os.name == "nt" else "__encore_unit_harness")
        before = binary.stat().st_mtime_ns
        print(run("--jobs", "8", "--report", "report-eight.json"), end="", flush=True)
        assert binary.stat().st_mtime_ns == before, "changing runtime jobs rebuilt the harness"
        report = json.loads((root / "report-eight.json").read_text(encoding="utf-8"))
        assert report["summary"]["passed"] == 10 and report["summary"]["failed"] == 0, report
    print("scheduler: metadata/archives, diamond, priority, no barriers, jobs=1/2/4/8, CPU/RAM, cancellation; package graph: no source parsing")


if __name__ == "__main__":
    main()

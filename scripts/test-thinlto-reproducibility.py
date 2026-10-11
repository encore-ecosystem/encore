#!/usr/bin/env python3
"""Verify actual extreme archives/binaries across staging paths and job counts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if sys.platform != "linux":
        print("ThinLTO cache contract uses the Linux LLD backend")
        return
    compiler = Path(sys.argv[1]).resolve()
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-thinlto-") as directory:
        scratch = Path(directory)
        snapshots = []
        for ordinal, jobs in enumerate((1, 4)):
            root = scratch / f"different path {ordinal}"
            dependency = root / "dependency"
            (root / "src").mkdir(parents=True)
            (dependency / "src").mkdir(parents=True)
            (root / "encore.toml").write_text(
                '[project]\nname="thin_application"\nversion="0.0.0"\n'
                'dependencies=["path@dependency"]\n')
            (dependency / "encore.toml").write_text(
                '[project]\nname="thin_dependency"\nversion="0.0.0"\ndependencies=[]\n')
            (dependency / "src/lib.enq").write_text(
                'pub fn message() -> str { ret "stable source identity" }\n')
            (root / "src/main.enq").write_text(
                'import thin_dependency::message\n'
                'fn main() -> u32 { ret if message().len() == 22 { 0 } else { 1 } }\n')
            environment = {**os.environ,
                           "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core"),
                           "ENCORE_BUILD_CACHE": str(root / "cache")}
            def build():
                result = subprocess.run(
                    [str(compiler), "build", "--profile", "extreme", "--jobs", str(jobs), "--timings"],
                    cwd=root, env=environment, capture_output=True, text=True, timeout=300)
                assert result.returncode == 0, result.stdout + result.stderr
                return json.loads((root / "target/extreme/encore-timings.json").read_text())
            build()
            binary = root / "target/extreme/thin_application"
            subprocess.run([str(binary)], check=True, timeout=10)
            archives = {}
            for marker in (root / "cache").glob("*/unit.complete"):
                ready = json.loads((marker.parent / "unit.ready").read_text())
                archives[ready["context"]["unit"]] = digest(marker.parent / "unit.erlib")
            assert "thin_dependency" in archives and "thin_application" in archives, archives
            snapshots.append((digest(binary), archives))
            cache = root / "target/extreme/thinlto-cache"
            assert cache.is_dir() and any(cache.iterdir()), "extreme link did not populate ThinLTO cache"
            before = binary.stat().st_mtime_ns
            report = build()
            assert report["link_cache_hit"] and binary.stat().st_mtime_ns == before, report
            # Change an ordinary body: reuse the application package, relink
            # through the existing ThinLTO cache, and execute the new binary.
            (dependency / "src/lib.enq").write_text(
                'pub fn message() -> str { let value = "stable source identity" ret value }\n')
            report = build()
            units = {unit["unit"]: unit for unit in report["units"]}
            assert units["thin_application"]["cache_hit"] and not units["thin_dependency"]["cache_hit"], report
            subprocess.run([str(binary)], check=True, timeout=10)
        assert snapshots[0] == snapshots[1], "extreme objects/binary depend on paths or worker count"
    print("ThinLTO: byte-identical archives/binary across paths/jobs=1/4, live bounded cache, no-op and body edit passed")


if __name__ == "__main__":
    main()

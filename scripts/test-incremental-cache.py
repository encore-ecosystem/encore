#!/usr/bin/env python3
"""Verify public binary builds against the current package-cache protocol."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root):
    app, dependency = root / "application", root / "dependency"
    for package in (app, dependency):
        (package / "src").mkdir(parents=True)
    (app / "encore.toml").write_text(
        '[project]\nname="cache_application"\nversion="0.0.0"\ndependencies=["path@../dependency"]\n')
    (dependency / "encore.toml").write_text(
        '[project]\nname="cache_dependency"\nversion="0.0.0"\ndependencies=[]\n')
    (dependency / "src/lib.enq").write_text('pub fn cached_value() -> u32 { ret 41 }\n')
    (app / "src/main.enq").write_text(
        'import core::option::Option as Opt\nimport cache_dependency::cached_value\n'
        'fn main() -> u32 { let value = Opt[u64]::Some(cached_value() as u64)\n'
        'ret if value.unwrap_or(0) == 41 { 0 } else { 1 } }\n')
    return app, dependency


def main():
    compiler = Path(sys.argv[1]).resolve()
    assert compiler.is_file(), compiler
    with tempfile.TemporaryDirectory(prefix="encore-cache-regression-") as directory:
        root = Path(directory)
        app, dependency = fixture(root)
        cache = root / "cache"
        environment = {**os.environ, "ENCORE_BUILD_CACHE": str(cache)}
        binary = app / "target/dev" / ("cache_application.exe" if os.name == "nt" else "cache_application")

        def build(project=app, jobs=2):
            result = subprocess.run([str(compiler), "build", "--jobs", str(jobs), "--timings"],
                                    cwd=project, env=environment, capture_output=True, text=True, timeout=240)
            assert result.returncode == 0, result.stdout + result.stderr
            report = json.loads((project / "target/dev/encore-timings.json").read_text())
            assert report["schema"] == 1 and report["total_ms"] >= 0, report
            return {item["unit"]: item for item in report["units"]}, report

        def executes(path=binary):
            result = subprocess.run([str(path)], capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result

        def committed_entries(unit):
            entries = []
            for marker in cache.glob("*/unit.complete"):
                try:
                    ready = json.loads((marker.parent / "unit.ready").read_text())
                except (OSError, ValueError):
                    # An older source identity can remain deliberately corrupt.
                    # It is not the entry this source revision will hydrate.
                    continue
                if ready["context"]["unit"] == unit:
                    entries.append(marker.parent)
            return entries

        first, _ = build()
        assert not first["cache_application"]["cache_hit"]
        executes()
        before, modified = digest(binary), binary.stat().st_mtime_ns
        second, report = build()
        assert all(item["cache_hit"] for item in second.values()) and report["link_cache_hit"], report
        assert digest(binary) == before and binary.stat().st_mtime_ns == modified

        # Native-only flag changes hydrate ready backend checkpoints before
        # workers start. Consumers must never see their ready receipts removed
        # or rewritten by producers regenerating archives.
        manifest = app / "encore.toml"
        original_manifest = manifest.read_text()
        previous_preload = environment.get("LD_PRELOAD")
        if sys.platform == "linux":
            guard = root / "readiness-guard.so"
            fixture_source = Path(__file__).resolve().parents[1] / "tests/native/build_readiness_guard.c"
            subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-shared", "-fPIC", str(fixture_source), "-ldl", "-o", str(guard)],
                           check=True, timeout=60)
            environment["LD_PRELOAD"] = str(guard) + (":" + previous_preload if previous_preload else "")
        for revision, jobs in enumerate((1, 4, 1, 4, 4, 1, 4, 4)):
            manifest.write_text(original_manifest + '\n[target]\ncompile-args=["-DREADY_REVISION=' +
                                str(revision) + '"]\n')
            units, report = build(jobs=jobs)
            for name in ("core", "cache_dependency"):
                assert not units[name]["cache_hit"] and units[name]["phases"]["backend_cache_hit"], report
            executes()
        if previous_preload is None:
            environment.pop("LD_PRELOAD", None)
        else:
            environment["LD_PRELOAD"] = previous_preload
        manifest.write_text(original_manifest)
        build()

        source = dependency / "src/lib.enq"
        source.write_text('pub fn cached_value() -> u32 { let base = 40 ret base + 1 }\n')
        body, _ = build()
        assert body["cache_application"]["cache_hit"] and not body["cache_dependency"]["cache_hit"], body
        executes()
        source.write_text('pub fn cached_value() -> u64 { ret 41 }\n')
        interface, _ = build()
        assert not interface["cache_application"]["cache_hit"], interface
        executes()
        expected = digest(binary)

        # Only disposable fixture output is removed.
        shutil.rmtree(app / "target")
        hydrated, _ = build()
        assert all(item["cache_hit"] for item in hydrated.values()), hydrated
        assert digest(binary) == expected
        executes()

        for name in ("unit.ermeta", "unit.ertemplate", "unit.errequirements", "unit.erlib", "unit.ready", "unit.complete"):
            entries = committed_entries("cache_application")
            assert entries, name
            for entry in entries:
                (entry / name).write_bytes(b"corrupt package cache payload\n")
            repaired, _ = build()
            assert not repaired["cache_application"]["cache_hit"], (name, repaired)
            executes()
            assert digest(binary) == expected

        for marker in cache.glob("*/unit.backend"):
            metadata = json.loads((marker.parent / "unit.ermeta").read_text())
            if metadata["context"]["unit"] == "cache_application":
                (marker.parent / "unit.erowned").write_bytes(b"invalid EHIR")
        for entry in committed_entries("cache_application"):
            (entry / "unit.erlib").write_bytes(b"invalid archive")
        repaired, _ = build()
        assert not repaired["cache_application"]["cache_hit"]
        executes()

        (app / "runtime.c").write_text(
            '#include "fixture.h"\n'
            '#if __has_include("optional.h")\n#include "optional.h"\n'
            '#else\n#define OPTIONAL_VALUE 0\n#endif\n'
            'int cache_marker(void) { return CACHE_VALUE + OPTIONAL_VALUE; }\n')
        (app / "fixture.h").write_text('#define CACHE_VALUE 1\n')
        build(jobs=1)
        native_before = digest(binary)
        (app / "fixture.h").write_text('#define CACHE_VALUE 2\n')
        units, report = build(jobs=4)
        assert all(item["cache_hit"] for item in units.values()) and not report["link_cache_hit"], report
        assert digest(binary) != native_before
        executes()

        # Dependency discovery must remain live: hashing only the previous
        # headers misses newly available __has_include branches.
        without_optional = digest(binary)
        optional = app / "optional.h"
        optional.write_text('#define OPTIONAL_VALUE 7\n')
        units, report = build(jobs=4)
        assert all(item["cache_hit"] for item in units.values()) and not report["link_cache_hit"], report
        assert digest(binary) != without_optional
        optional.unlink()
        build(jobs=1)
        assert digest(binary) == without_optional

        # Failure in one native scan must reap siblings and preserve the last
        # working executable, rather than publishing a partial link.
        runtime_source = (app / "runtime.c").read_text()
        (app / "runtime.c").write_text('#include "missing-required-header.h"\n')
        failed = subprocess.run([str(compiler), "build", "--jobs", "4"], cwd=app,
                                env=environment, capture_output=True, text=True, timeout=60)
        assert failed.returncode != 0 and "missing-required-header.h" in failed.stderr, failed
        assert digest(binary) == without_optional
        executes()
        (app / "runtime.c").write_text(runtime_source)
        build(jobs=4)

        clean, clean_dependency = fixture(root / "clean")
        (clean_dependency / "src/lib.enq").write_text(source.read_text())
        (clean / "runtime.c").write_text((app / "runtime.c").read_text())
        (clean / "fixture.h").write_text((app / "fixture.h").read_text())
        environment["ENCORE_BUILD_CACHE"] = str(root / "empty-cache")
        build(clean)
        clean_binary = clean / "target/dev" / binary.name
        executes(clean_binary)
        assert digest(clean_binary) == digest(binary), "incremental/clean or path-dependent binary mismatch"
    print("package cache: no-op, native-flag readiness stability, body/interface edits, hydration, six corrupt payloads, backend recovery, "
          "parallel/serial native headers, optional-header discovery, scan failure and clean/path parity passed")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise shared unit compilation, process isolation, filters and cache reuse."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    compiler = str(Path(sys.argv[1] if len(sys.argv) > 1 else "target/extreme/encore").resolve())
    with tempfile.TemporaryDirectory(prefix="encore-unit-harness-") as scratch:
        root = Path(scratch) / "workspace with spaces"
        root.mkdir()
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "dependency/src").mkdir(parents=True)
        (root / "dependency/encore.toml").write_text(
            '[project]\nname="harness_dependency"\nversion="0.0.0"\ndependencies=[]\n')
        (root / "dependency/src/lib.enq").write_text(
            'pub fn answer() -> u32 { ret 42_u32 }\n'
            '#attr(test)\nfn dependency_test_is_not_run() -> bool { ret false }\n')
        (root / "encore.toml").write_text(
            '[project]\nname="harness_probe"\nversion="0.0.0"\n'
            'dependencies=["path@dependency"]\n')
        (root / "runtime.c").write_text(
            '#include <stdint.h>\nstatic uint32_t calls;\n'
            'uint32_t harness_tick(void) { return ++calls; }\n')
        (root / "src/lib.enq").write_text('''import refrain::left::marker
import refrain::right::other_marker
import harness_dependency::answer
import core::panic::panic
extern fn harness_tick() -> u32
fn __encore_unit_test_0() -> bool { ret false }
#attr(test)
fn isolated_one() -> bool { unsafe { ret harness_tick() == 1_u32 } }
#attr(test)
fn isolated_two() -> bool { unsafe { ret harness_tick() == 1_u32 } }
#attr(test)
fn passes() -> bool { ret marker() && other_marker() && answer() == 42_u32 }
#attr(test)
fn fails() -> bool { ret false }
#attr(test)
fn panics() -> bool { panic("harness panic evidence") ret true }
#attr(test)
fn invalid_parameter(value: bool) -> bool { ret value }
#attr(test)
fn invalid_return() -> u32 { ret 0_u32 }
#attr(test)
fn invalid_generic[T]() -> bool { ret true }
#attr(test)
#cfg(target_os = "harness-impossible-os")
fn disabled_test() -> bool { ret missing_disabled_symbol() }
#attr(test)
async fn invalid_async() -> bool { ret true }
''')
        for name, marker in (("left", "marker"), ("right", "other_marker")):
            (root / "src" / f"{name}.enq").write_text(f'''pub fn {marker}() -> bool {{ ret true }}
fn private_helper() -> bool {{ ret true }}
#attr(test)
fn same_name() -> bool {{ ret private_helper() }}
''')
        (root / "tests/standalone.enq").write_text('fn main() -> u32 { ret 0_u32 }\n')
        (root / "tests/negative.enq").write_text(
            '// @expect.compile_error=unknown\nfn main() -> u32 { let value: MissingType = 1_u32 ret 0_u32 }\n')
        environment = {**os.environ, "ENCORE_REGISTRY_CACHE": str(root / "registry")}

        def run(*arguments, expected=0):
            result = subprocess.run([compiler, "test", *arguments], cwd=root, env=environment,
                                    capture_output=True, text=True, timeout=180)
            output = result.stdout + result.stderr
            assert result.returncode == expected, output
            return output

        listed = run("--list", "--format", "json")
        planned = json.loads(listed)
        assert len(planned) == 13 and not any("dependency_test" in item or "disabled_test" in item for item in planned), planned
        assert not (root / "target/tests/bin").exists(), "listing compiled tests"
        output = run("--jobs", "2", "--report", "report.json", expected=1)
        assert (root / "report.json").exists(), output
        report = json.loads((root / "report.json").read_text())
        records = {item["id"].split("::")[-1]: item for item in report["tests"]}
        assert report["summary"]["passed"] == 7 and report["summary"]["failed"] == 6, report
        for name in ("isolated_one", "isolated_two", "passes", "same_name"):
            assert records[name]["status"] == "passed", records[name]
        duplicates = [item for item in report["tests"] if item["id"].endswith("::same_name")]
        assert len(duplicates) == 2 and all(item["status"] == "passed" for item in duplicates), duplicates
        assert "harness panic evidence" in records["panics"]["message"], records["panics"]
        for name in ("invalid_parameter", "invalid_return", "invalid_generic", "invalid_async"):
            assert "test must be fn() -> bool" in records[name]["message"], records[name]
        binary = root / "target/tests/bin/__encore_unit_harness"
        if os.name == "nt":
            binary = binary.with_suffix(".exe")
        assert subprocess.run([str(binary), planned[0]], cwd=root).returncode == 0
        before = binary.stat().st_mtime_ns
        run("--filter", "passes", "--report", "filtered.json")
        assert binary.stat().st_mtime_ns == before, "filter rebuilt the shared harness"
        assert len(json.loads((root / "filtered.json").read_text())["tests"]) == 1
        run("--filter", "same_name", "--jobs", "2")
        assert binary.stat().st_mtime_ns == before, "duplicate-name tests rebuilt the harness"
        run("--filter", "invalid_parameter", "--report", "invalid.json", expected=1)
        assert binary.stat().st_mtime_ns == before, "invalid signature rebuilt the harness"
        run("--filter", "no_matching_test", "--report", "empty.json")
        assert not json.loads((root / "empty.json").read_text())["tests"]
        assert binary.stat().st_mtime_ns == before, "empty selection rebuilt the harness"
        run("--filter", "isolated_", "--jobs", "1")
        run("--filter", "isolated_", "--jobs", "2")
        # The package name is metadata, not an identifier in generated code.
        manifest = root / "encore.toml"
        manifest.write_text(manifest.read_text().replace('name="harness_probe"', 'name="harness-probe"'))
        run("--filter", "same_name", "--jobs", "2")
        manifest.write_text(manifest.read_text().replace('name="harness-probe"', 'name="harness_probe"'))
        assert subprocess.run([str(binary), "unknown"], cwd=root).returncode == 2
        assert subprocess.run([str(binary)], cwd=root).returncode == 2
        # Source edits must invalidate the harness, even for the same filter.
        source = root / "src/lib.enq"
        source.write_text(source.read_text().replace('fn passes() -> bool { ret marker()',
                                                    'fn passes() -> bool { ret false && marker()'))
        run("--filter", "passes", expected=1)
        assert binary.stat().st_mtime_ns != before, "source edit reused a stale harness"
        # Binary packages must replace, not execute, their application main.
        source.rename(root / "src/main.enq")
        with (root / "src/main.enq").open("a") as handle:
            handle.write('\nfn main() -> u32 { panic("application main must not run") ret 1_u32 }\n')
        run("--filter", "isolated_", "--jobs", "2")
        # A failed shared compilation must not terminate the reporting parent
        # or prevent the independent standalone tests from completing.
        source = root / "src/main.enq"
        source.write_text(source.read_text().replace('ret false && marker()', 'ret missing_harness_function() && marker()'))
        run("--report", "compile-error.json", expected=1)
        broken = json.loads((root / "compile-error.json").read_text())
        assert broken["summary"]["passed"] == 2 and broken["summary"]["failed"] == 11, broken
        assert (root / "target/tests/__encore_unit_harness.output.txt").exists()
    print("Shared harness: isolation, failures, panic, signatures, duplicate names, filters, cache, source edits, standalone/negative and binary packages passed")


if __name__ == "__main__":
    main()

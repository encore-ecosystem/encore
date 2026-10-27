#!/usr/bin/env python3
"""Exercise real native plugin libraries without requiring an Encore bootstrap."""
import argparse
from contextlib import contextmanager
import json
import hashlib
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--target")
    parser.add_argument("--compiler", type=lambda value: str(Path(value).resolve()))
    parser.add_argument("--ascii-projects", action="store_true", help="Use an ASCII build root when debugging a bootstrap compiler")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep generated projects for debugging failed checks")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--profile", choices=("dev", "extreme"))
    parser.add_argument("--suite", choices=("all", "native", "formatter", "resources", "dto"), default="all")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.suite in ("formatter", "resources", "dto") and not args.compiler:
        parser.error("the selected suite requires --compiler")
    root = Path(__file__).resolve().parents[1]
    directory = root / "target/native-plugins"
    directory.mkdir(parents=True, exist_ok=True)
    windows = os.name == "nt"
    darwin = sys.platform == "darwin"
    profile = args.profile or ("extreme" if args.benchmark else "dev")
    compiler_identity = dict(path=args.compiler, sha256=hashlib.sha256(Path(args.compiler).read_bytes()).hexdigest()) if args.compiler else None
    records = []

    @contextmanager
    def scratch_directory(prefix):
        if args.keep_artifacts:
            scratch = tempfile.mkdtemp(prefix=prefix, dir=directory)
            print(json.dumps(dict(artifacts=scratch)), flush=True)
            yield scratch
        else:
            with tempfile.TemporaryDirectory(prefix=prefix, dir=directory) as scratch:
                yield scratch

    def write_report(passed):
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(dict(passed=passed, platform=sys.platform, profile=profile, compiler=compiler_identity, checks=records), indent=2) + "\n")

    write_report(False)

    def run(name, command, cwd=None, environment=None, expected=0, diagnostic=None):
        start = time.monotonic()
        result = subprocess.run(command, cwd=cwd or root, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        record = dict(name=name, exit_code=result.returncode, seconds=round(time.monotonic() - start, 4),
                      stdout=result.stdout, stderr=result.stderr)
        if expected:
            record["expected_exit_code"] = expected
        records.append(record)
        write_report(False)
        print(json.dumps(record), flush=True)
        if result.returncode != expected or (diagnostic and diagnostic not in result.stdout + result.stderr):
            raise SystemExit(f"native plugin check failed: {name}")

    if args.suite in ("all", "native"):
        with scratch_directory("native plugins плагины ") as scratch:
            out = Path(scratch)
            cc = [args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror"]
            if args.target:
                cc += ["--target=" + args.target]
            libraries = []
            for name, define in (("v1", None), ("v2", "PLUGIN_REVISION=2"),
                                 ("bad-abi", "PLUGIN_BAD_ABI=1"), ("bad-state", "PLUGIN_BAD_STATE=1"),
                                 ("bad-signature", "PLUGIN_BAD_SIGNATURE=1")):
                path = out / (name + (".dll" if windows else ".dylib" if darwin else ".so"))
                flags = [] if windows else ["-fPIC", "-fvisibility=hidden"]
                flags += ["-dynamiclib" if darwin else "-shared"]
                if define:
                    flags += ["-D" + define]
                run("build-" + name, cc + flags + ["packages/platform/tests/plugins/fixture.c", "-o", str(path)])
                libraries.append(str(path))
            program = out / ("manager.exe" if windows else "manager")
            flags = ["-lshell32"] if windows else ["-pthread"] + ([] if darwin else ["-ldl"])
            run("build-manager", cc + ["packages/platform/plugin_runtime.c", "packages/platform/tests/plugins/manager.c",
                                       "-o", str(program)] + flags)
            run("manager", [str(program), *libraries])
            sdk = out / ("sdk.exe" if windows else "sdk")
            strip = "-Wl,-dead_strip" if darwin else "-Wl,--gc-sections"
            sdk_flags = flags + ([] if windows else ["-lm"])
            run("build-sdk", cc + ["-ffunction-sections", "-fdata-sections", strip,
                "packages/platform/tests/plugins/sdk.c", "packages/core/runtime.c", "-o", str(sdk)] + sdk_flags)
            run("sdk", [str(sdk)])
            if args.benchmark:
                benchmark = out / ("benchmark.exe" if windows else "benchmark")
                bench_flags = flags + (["-lpsapi"] if windows else [])
                run("build-benchmark", cc + ["packages/platform/tests/plugins/benchmark.c", "-o", str(benchmark)] + bench_flags)
                run("benchmark", [str(benchmark), libraries[0]])
    if args.compiler:
        environment = os.environ.copy()
        environment["ENCORE_CORE_DIR"] = str(root / "packages/core")
        environment.setdefault("ENCORE_BUILD_CACHE", str(directory / "encore-cache"))
    if args.compiler and args.suite in ("all", "formatter"):
        example = root / "examples/native-plugins"
        for package in ("formatter-v1", "formatter-v2", "host"):
            if package != "host":
                run("check-encore-" + package, [args.compiler, "check"], cwd=example / package, environment=environment)
            run("build-encore-" + package, [args.compiler, "build", "--profile", profile, "--jobs", "2"],
                cwd=example / package, environment=environment)
        library = ("" if windows else "lib") + "formatter_plugin" + (".dll" if windows else ".dylib" if darwin else ".so")
        environment["PLUGIN_V1"] = str(example / "formatter-v1/target" / profile / library)
        environment["PLUGIN_V2"] = str(example / "formatter-v2/target" / profile / library)
        program = example / "host/target" / profile / ("formatter_host.exe" if windows else "formatter_host")
        run("encore-host-reload", [str(program)], environment=environment)
        if not windows and not darwin:
            result = subprocess.check_output(["nm", "-D", "--defined-only", environment["PLUGIN_V1"]], text=True)
            exports = [line.split()[-1] for line in result.splitlines() if line.strip()]
            if exports != ["encore_plugin_entry_v1"]:
                raise SystemExit("plugin leaks native symbols: " + repr(exports))
    if args.compiler and args.suite in ("all", "resources"):
        fixtures = root / "tests/fixtures/native_plugins"
        for representation in ("inline", "heap"):
            with scratch_directory(("typed-plugins-" if args.ascii_projects else "typed plugins ресурсы ") + representation + " ") as scratch:
                suite = Path(scratch)
                for name in ("api", "host"):
                    shutil.copytree(fixtures / name, suite / name)
                    manifest = suite / name / "encore.toml"
                    manifest.write_text(manifest.read_text().replace("../../../../packages/std", (root / "packages/std").as_posix()))
                for name, revision, offset, bad_state in (("v1", "v1", 0, False), ("v2", "v2", 100, False), ("bad-state", "bad", 0, True)):
                    package = suite / name
                    shutil.copytree(fixtures / "implementation", package)
                    manifest = package / "encore.toml"
                    manifest.write_text(manifest.read_text().replace("../../../../packages/std", (root / "packages/std").as_posix()))
                    source = package / "src/lib.enq"
                    text = source.read_text().replace("__REV__", revision).replace("__OFFSET__", str(offset)).replace("__BAD_STATE__", "true" if bad_state else "false")
                    if representation == "heap":
                        text = text.replace("Result[StateCounter, str]", "Result[StateCounter<H>, str]")
                        text = text.replace("value: StateCounter)", "value: StateCounter<H>)")
                        text = text.replace("Result::Ok(StateCounter {", "Result::Ok(StateCounter<H> {")
                        text = text.replace("::new(LeafCounter[bool] {", "::new(LeafCounter[bool]<H> {")
                        text = text.replace("::new(LeafCounter[Tag] {", "::new(LeafCounter[Tag]<H> {")
                        text = text.replace("{Resource, StateSnapshot}", "{Resource as Handle, StateSnapshot}")
                        text = text.replace("Resource[", "Handle[")
                    source.write_text(text)
                    if name == "v1":
                        run("emit-stateful-" + representation, [args.compiler, "build", "--emit", "ehir"], cwd=package, environment=environment)
                    run("build-stateful-" + representation + "-" + name, [args.compiler, "build", "--profile", profile, "--jobs", "2"], cwd=package, environment=environment)
                run("build-stateful-host-" + representation, [args.compiler, "build", "--profile", profile, "--jobs", "2"], cwd=suite / "host", environment=environment)
                library = ("" if windows else "lib") + "counter_plugin" + (".dll" if windows else ".dylib" if darwin else ".so")
                unicode_libraries = suite / "плагины с пробелами"
                unicode_libraries.mkdir()
                for name, variable in (("v1", "COUNTER_V1"), ("v2", "COUNTER_V2"), ("bad-state", "COUNTER_BAD_STATE")):
                    destination = unicode_libraries / ("версия-" + name + Path(library).suffix)
                    shutil.copy2(suite / name / "target" / profile / library, destination)
                    environment[variable] = str(destination)
                program = suite / "host/target" / profile / ("counter_host.exe" if windows else "counter_host")
                run("stateful-resources-" + representation, [str(program)], environment=environment)
    if args.compiler and args.suite in ("all", "dto"):
        fixtures = root / "tests/fixtures/native_plugins"
        with scratch_directory("dto plugins данные ") as scratch:
            suite = Path(scratch)
            for name in ("dto-api", "dto-implementation", "dto-host"):
                shutil.copytree(fixtures / name, suite / name)
                manifest = suite / name / "encore.toml"
                manifest.write_text(manifest.read_text().replace("../../../../packages/std", (root / "packages/std").as_posix()))
            for name in ("dto-implementation", "dto-host"):
                run("build-" + name, [args.compiler, "build", "--profile", profile, "--jobs", "2"], cwd=suite / name, environment=environment)
            library = ("" if windows else "lib") + "dto_plugin" + (".dll" if windows else ".dylib" if darwin else ".so")
            environment["DTO_PLUGIN"] = str(suite / "dto-implementation/target" / profile / library)
            program = suite / "dto-host/target" / profile / ("dto_host.exe" if windows else "dto_host")
            if args.benchmark:
                environment["PLUGIN_BENCHMARK"] = "1"
            run("generic-interface-dtos", [str(program)], environment=environment)
            manifest = suite / "dto-implementation/encore.toml"
            original = manifest.read_text()
            assert "Marker[u32]" in original
            try:
                manifest.write_text(original.replace("Marker[u32]", "Marker[str]"))
                run("reject-wrong-generic-implementation", [args.compiler, "build", "--jobs", "2"],
                    cwd=suite / "dto-implementation", environment=environment, expected=1, diagnostic="plugin-implementation")
            finally:
                manifest.write_text(original)
    write_report(True)


if __name__ == "__main__":
    main()

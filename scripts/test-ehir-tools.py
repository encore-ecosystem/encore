#!/usr/bin/env python3
"""Check the standalone EHIR interpreter and native debug objects."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "packages/ehir-interpret/tests/fixtures"
CORE = ROOT / "packages/core"
PROGRAMS = {
    "values": (42, ""),
    "control-flow": (42, ""),
    "generator": (0, "99\n7\n7\n13\n13\n7\n13\n"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--lldb", help="Build and test debug objects using this LLDB")
    args = parser.parse_args()
    environment = {**os.environ, "ENCORE_CORE_DIR": str(CORE)}

    def run(command, *, cwd=ROOT, expected=0, env=environment):
        result = subprocess.run(
            [str(arg) for arg in command], cwd=cwd, env=env,
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != expected:
            raise RuntimeError(
                f"{command} exited with {result.returncode}, expected {expected}\n"
                f"{result.stdout}{result.stderr}"
            )
        return result

    def build(package):
        cwd = ROOT / "packages" / package
        run([args.compiler.resolve(), "build"], cwd=cwd)
        suffix = ".exe" if os.name == "nt" else ""
        return cwd / "target/dev" / (package + suffix)

    interpret = build("ehir-interpret")
    assert run([interpret, "--help"]).stdout.startswith("Usage: ehir-interpret")
    with tempfile.TemporaryDirectory(prefix="ehir tools ") as scratch:
        work = Path(scratch)
        for name, (status, output) in PROGRAMS.items():
            result = run([interpret, FIXTURES / (name + ".ehir")], expected=status)
            assert result.stdout == output, (name, result.stdout)

        invalid = work / "unsupported.ehir"
        invalid.write_text(
            'extern fn native() -> u32\n'
            'fn main() -> u32 {\n$entry:\n'
            '    value: u32 = call native()\n    ret value: u32\n}\n'
        )
        error = run([interpret, invalid], expected=1).stderr
        assert f"{invalid}:3: main / $entry" in error and "unsupported function native" in error, error
        invalid.write_text(
            'fn main() -> u32 {\n$entry:\n    value: u32 = wrong\n    ret value: u32\n}\n'
        )
        error = run([interpret, invalid], expected=1).stderr
        assert str(invalid) in error and "panic:" not in error, error
        print("EHIR interpreter passed control flow, generics, aggregates, generators and diagnostics", flush=True)

        if not args.lldb:
            return
        debug = build("ehir-dbg")
        cc = environment.get("CC", "clang")
        bridge = work / "print.c"
        bridge.write_text(
            '#include <inttypes.h>\n#include <stdio.h>\n'
            'void ehir_println_u64(uint64_t value) { printf("%" PRIu64 "\\n", value); }\n'
        )

        def stop_at(executable, file, line, *commands):
            result = run([
                args.lldb, "--no-lldbinit", "--batch",
                "-o", "settings set target.disable-aslr false",
                "-o", f"breakpoint set --file {file} --line {line}", "-o", "run",
                *(item for command in commands for item in ("-o", command)),
                executable,
            ])
            assert "stop reason = breakpoint" in result.stdout, result.stdout
            assert f"{file}:{line}:" in result.stdout, result.stdout
            return result.stdout

        for name, (status, output) in PROGRAMS.items():
            source = work / (name + ".ehir")
            shutil.copyfile(FIXTURES / source.name, source)
            obj = work / (name + ".o")
            executable = work / name
            run([debug, source, "-o", obj])
            run([cc, "-g", obj, CORE / "runtime.c", bridge, "-lm", "-pthread", "-o", executable])
            result = run([executable], expected=status)
            assert result.stdout == output, (name, result.stdout)
            if name == "values":
                debug_output = stop_at(executable, source.name, 6, "frame variable answer")
                assert re.search(r"\banswer = 42\b", debug_output), debug_output
            if name == "control-flow":
                lines = source.read_text().splitlines()
                line = next(i for i, text in enumerate(lines, 1) if "total: u32 = add" in text)
                debug_output = stop_at(executable, source.name, line, "frame variable limit n")
                assert re.search(r"\blimit = 6\b", debug_output), debug_output
                assert re.search(r"\bn = 6\b", debug_output), debug_output
            if name == "generator":
                lines = source.read_text().splitlines()
                line = next(i for i, text in enumerate(lines, 1) if "yield next:" in text)
                debug_output = stop_at(executable, source.name, line, "thread backtrace")
                assert "resume" in debug_output and "main at generator.ehir:" in debug_output, debug_output

        original = obj.read_bytes()
        run([debug, source, "-o", obj], expected=1, env={**environment, "CC": str(work / "missing-clang")})
        assert obj.read_bytes() == original
        assert not list(work.glob("*.ehir-dbg-*")), "debugger staging directory leaked"
        print("EHIR native debug objects passed output parity, breakpoints, variables and generator backtrace")


if __name__ == "__main__":
    main()

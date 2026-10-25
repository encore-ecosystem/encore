#!/usr/bin/env python3
"""Check live frames before completion, terminal cleanup, and plain CLI output."""

import argparse
import os
from pathlib import Path
import json
import signal
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
FRAMES = tuple(frame.encode() for frame in "⠋⠙⠹⠸")


def native_tests(cc, temporary):
    if os.name != "posix":
        print("PTY renderer checks require a POSIX terminal")
        return
    import fcntl
    import pty
    import select
    import struct
    import termios

    driver = temporary / "terminal-progress"
    dead_strip = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
    subprocess.run([
        cc, "-std=c11", "-O1", "-ffunction-sections", "-fdata-sections", dead_strip,
        str(ROOT / "tests/terminal_progress_native.c"),
        str(ROOT / "packages/rich/runtime.c"), str(ROOT / "packages/platform/runtime.c"),
        "-pthread", "-o", str(driver),
    ], check=True)
    # Older published target kits have no output-observer entry point. Rename
    # just that definition to exercise a genuinely absent optional symbol.
    legacy_platform = temporary / "legacy-platform.o"
    subprocess.run([
        cc, "-std=c11", "-O1", "-ffunction-sections", "-fdata-sections",
        "-Dencore_io_set_write_observer=encore_test_legacy_observer",
        "-c", str(ROOT / "packages/platform/runtime.c"), "-o", str(legacy_platform),
    ], check=True)
    legacy_driver = temporary / "legacy-terminal-progress"
    subprocess.run([
        cc, "-std=c11", "-O1", "-ffunction-sections", "-fdata-sections", dead_strip,
        str(ROOT / "tests/terminal_progress_native.c"),
        str(ROOT / "packages/rich/runtime.c"), str(legacy_platform),
        "-pthread", "-o", str(legacy_driver),
    ], check=True)
    environment = dict(os.environ, TERM="xterm-256color", NO_COLOR="1")
    plain = subprocess.run([str(driver)], input=b"nnnnn", capture_output=True, env=environment, timeout=10)
    assert plain.returncode == 0, plain
    assert plain.stdout == b"READY\nUSER PROGRAM\n", plain.stdout
    assert plain.stderr == b"diagnostic: complete line\n", plain.stderr

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 90, 0, 0))
    process = subprocess.Popen([str(driver)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=slave, env=environment)
    os.close(slave)

    def read_until(predicate):
        result = b""
        deadline = time.monotonic() + 10
        while not predicate(result):
            assert process.poll() is None, (process.returncode, result)
            assert time.monotonic() < deadline, result
            if select.select([master], [], [], 0.2)[0]:
                result += os.read(master, 65536)
        return result

    def advance():
        process.stdin.write(b"n")
        process.stdin.flush()

    def distinct_frames(value):
        return sum(frame in value for frame in FRAMES) >= 2

    try:
        first = read_until(lambda value: b"Compiling packages" in value and
                           b"more active" in value and distinct_frames(value))
        assert b"[0/8]" in first and "中文".encode() in first, first
        assert b"\x1b[36m" not in first, first
        # Shrink while active: rows and Unicode names must stay bounded.
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 6, 32, 0, 0))
        advance()
        second = read_until(lambda value: b"diagnostic: complete line" in value and
                            b"[1/8]" in value and distinct_frames(value))
        assert b"[2/8]" not in second, second
        advance()
        third = read_until(lambda value: b"Linking" in value and distinct_frames(value))
        assert b"[1/8]" not in third.split(b"Linking", 1)[1], third
        advance()
        assert process.stdout.readline() == b"READY\n"
        assert process.stdout.readline() == b"USER PROGRAM\n"
        # Drain the final clear and prove the renderer stays stopped while the
        # user program would run. This wait is a behavioral observation.
        while select.select([master], [], [], 0.2)[0]:
            os.read(master, 65536)
        assert not select.select([master], [], [], 0.25)[0]
        advance()
        fourth = read_until(lambda value: b"Second operation" in value and distinct_frames(value))
        assert b"STALE REPORTER" not in fourth, fourth
        advance()
        stdout, _ = process.communicate(timeout=10)
        assert process.returncode == 0 and stdout == b"", (process.returncode, stdout)
        (first + second + third + fourth).decode("utf-8")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    # Dumb terminals and older runtimes must receive plain diagnostics.
    for executable, term in ((driver, "dumb"), (legacy_driver, "xterm-256color")):
        master, slave = pty.openpty()
        process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=slave, env=dict(environment, TERM=term))
        os.close(slave)
        try:
            stdout, _ = process.communicate(input=b"nnnnn", timeout=10)
            output = b""
            while True:
                try:
                    chunk = os.read(master, 65536)
                    if not chunk:
                        break
                    output += chunk
                except OSError as error:
                    if error.errno != 5:
                        raise
                    break
            assert process.returncode == 0 and stdout == b"READY\nUSER PROGRAM\n"
            assert b"\x1b" not in output, output
        finally:
            os.close(master)

    master, slave = pty.openpty()
    process = subprocess.Popen([str(driver)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=slave, env=environment)
    os.close(slave)
    try:
        interrupted = read_until(distinct_frames)
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=10)
        assert process.returncode == -signal.SIGINT
        assert b"\x1b[?25l" not in interrupted, "cursor must remain visible on interruption"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    print("Native live frames, parallel rows, resize, diagnostics, lifecycle and plain output: passed")


def cli_tests(compiler, temporary):
    root = temporary / "project"
    (root / "src").mkdir(parents=True)
    dependency = (ROOT / "packages/std").as_posix()
    (root / "encore.toml").write_text(
        '[project]\nname = "terminal_probe"\nversion = "0.0.0"\n'
        f'dependencies = ["path@{dependency}"]\n', newline="\n")
    (root / "src/main.enq").write_text(
        'import std::io::println\nimport std::os::file_exists\nimport std::time::sleep_ms\n\n'
        'fn main() -> u32 {\n    println("USER PROGRAM")\n'
        '    while !file_exists("release-user") {\n'
        '        let _wait = sleep_ms(10_u64)\n    }\n    ret 0_u32\n}\n', newline="\n")
    (root / "release-user").touch()
    environment = dict(os.environ, ENCORE_CORE_DIR=str(ROOT / "packages/core"),
                       ENCORE_BUILD_CACHE=str(temporary / "cache"),
                       ENCORE_INDEX_URL="http://127.0.0.1:9/index")
    for arguments in (["check", "--format", "json"], ["lint", "--format", "json"],
                      ["format", "--check"], ["test", "--list"], ["sync"],
                      ["build", "--jobs", "1"], ["run"]):
        result = subprocess.run([compiler, *arguments], cwd=root, env=environment,
                                capture_output=True, timeout=120)
        assert result.returncode == 0, (arguments, result.stdout, result.stderr)
        assert b"\x1b" not in result.stdout + result.stderr, (arguments, result)
    print("Redirected build/run/tooling/dependency CLI contracts: passed")
    if os.name == "posix":
        cli_terminal_tests(compiler, root, environment)


def cli_terminal_tests(compiler, root, environment):
    import fcntl
    import pty
    import select
    import struct
    import termios

    with (root / "src/main.enq").open("a", newline="\n") as source:
        source.write('\n#attr(test)\nfn progress_unit() -> bool {\n'
                     '    let _wait = sleep_ms(400_u64)\n    ret true\n}\n')
    (root / "tests").mkdir()
    for name in ("progress_a", "progress_b"):
        (root / "tests" / (name + ".enq")).write_text(
            'import std::time::sleep_ms\n\nfn main() -> u32 {\n'
            '    let _wait = sleep_ms(400_u64)\n    ret 0_u32\n}\n', newline="\n")

    def launch(arguments):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 16, 100, 0, 0))
        process = subprocess.Popen([compiler, *arguments], cwd=root,
                                   env=dict(environment, TERM="xterm-256color"),
                                   stdout=subprocess.PIPE, stderr=slave)
        os.close(slave)
        return process, master

    def collect(process, master, observe):
        output = b""
        observed_running = False
        deadline = time.monotonic() + 120
        while True:
            assert time.monotonic() < deadline, output[-2000:]
            if select.select([master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno != 5:
                        raise
                    break
                if not chunk:
                    break
                output += chunk
                if observe(output) and sum(frame in output for frame in FRAMES) >= 2:
                    observed_running |= process.poll() is None
        stdout, _ = process.communicate(timeout=10)
        assert process.returncode == 0, (output, stdout)
        assert observed_running, output
        return output

    process, master = launch(["build", "--profile", "release", "--jobs", "2"])
    try:
        collect(process, master, lambda value: b"Compiling packages" in value and b"platform" in value)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)

    for emit in ("llvm-ir", "object"):
        process, master = launch(["build", "--emit", emit, "--jobs", "2"])
        try:
            collect(process, master, lambda value: b"Resolving" in value or b"Generating" in value)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    for jobs in ("1", "2"):
        report = root / ("report-" + jobs + ".json")
        process, master = launch(["test", "--jobs", jobs, "--report", str(report)])
        try:
            collect(process, master, lambda value: b"progress_a.enq" in value and b"progress_unit" in value)
            summary = json.loads(report.read_text())
            assert summary["summary"]["failed"] == 0 and summary["summary"]["selected"] == 3, summary
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    # A file barrier keeps the child alive until the terminal handoff has been
    # checked, regardless of runner speed or scheduling delays.
    release = root / "release-user"
    release.unlink()
    process, master = launch(["run"])
    try:
        assert select.select([process.stdout], [], [], 120)[0]
        assert process.stdout.readline() == b"USER PROGRAM\n"
        while select.select([master], [], [], 0.05)[0]:
            os.read(master, 65536)
        assert process.poll() is None
        assert not select.select([master], [], [], 0.2)[0], "animation survived user program handoff"
        release.touch()
        stdout, _ = process.communicate(timeout=10)
        assert process.returncode == 0 and stdout == b"", stdout
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    print("Real serial/parallel test events and user program terminal handoff: passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("ENCORE_CC", shutil.which("clang") or "cc"))
    parser.add_argument("--compiler", type=lambda value: str(Path(value).resolve()))
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore-terminal-") as directory:
        temporary = Path(directory)
        native_tests(arguments.cc, temporary)
        if arguments.compiler:
            cli_tests(arguments.compiler, temporary)


if __name__ == "__main__":
    main()

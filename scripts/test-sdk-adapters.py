#!/usr/bin/env python3
"""Check opt-in Rich adapters and shared TTY/NO_COLOR policy in native CI."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
compiler = Path(sys.argv[1]).resolve()
fixture = root / "tests/fixtures/sdk_adapters"
subprocess.run([str(compiler), "build", "--profile", "dev", "--jobs", "2"], cwd=fixture, check=True)
binary = fixture / "target/dev" / ("sdk_adapters.exe" if os.name == "nt" else "sdk_adapters")
environment = dict(os.environ, TERM="xterm-256color")
environment.pop("NO_COLOR", None)
result = subprocess.run([str(binary)], capture_output=True, env=environment, check=True)
assert b"adapter-ready" in result.stdout and b"console-ready" in result.stdout
assert b"\x1b[" not in result.stdout, result.stdout
if os.name == "posix":
    import pty
    for no_color, term, expected in ((None, "xterm", True), ("1", "xterm", False),
                                     ("", "xterm", True), (None, "dumb", False)):
        master, slave = pty.openpty()
        env = dict(environment, TERM=term)
        if no_color is not None:
            env["NO_COLOR"] = no_color
        process = subprocess.Popen([str(binary)], stdout=slave, stderr=slave, env=env)
        os.close(slave)
        output = b""
        try:
            while True:
                try:
                    chunk = os.read(master, 8192)
                except OSError as error:
                    if error.errno == 5:
                        break
                    raise
                if not chunk:
                    break
                output += chunk
        finally:
            os.close(master)
        assert process.wait(timeout=30) == 0
        assert (b"\x1b[" in output) == expected, (no_color, term, output)
print("Rich JSON/logging opt-in, redirection, TTY, NO_COLOR and TERM: ok")

# Compile interactive examples without running their prompt loops. Each uses
# the same consumer manifest and explicitly declares json/log/std dependencies.
entry = fixture / "src/main.enq"
original = entry.read_bytes()
try:
    for source in sorted((root / "packages/rich/examples").glob("*.enq")):
        entry.write_bytes(source.read_bytes())
        subprocess.run([str(compiler), "build", "--profile", "dev", "--jobs", "2"], cwd=fixture, check=True)
        print("Rich example build:", source.name, "ok", flush=True)
finally:
    entry.write_bytes(original)

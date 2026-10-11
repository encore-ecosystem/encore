#!/usr/bin/env python3
"""Check real guarded supervisors for concurrent log and diagnostic isolation."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    compiler = Path(sys.argv[1]).resolve()
    processes = []
    with tempfile.TemporaryDirectory(prefix="encore-tool-isolation-") as directory:
        root = Path(directory) / "working directory with spaces"
        root.mkdir()
        release = root / "release"
        # A barrier ensures all eight tools hold their log files concurrently.
        # Deadlines only guard hangs; no elapsed-time performance assertion.
        code = (
            "import pathlib,sys,time; index=int(sys.argv[1]); "
            "pathlib.Path(f'ready-{index}').write_text('ready'); "
            "\nwhile not pathlib.Path('release').exists(): time.sleep(.005)\n"
            "print(f'output-{index}'); print(f'error-{index}',file=sys.stderr); "
            "raise SystemExit(17 if index == 3 else 0)"
        )
        try:
            for index in range(8):
                processes.append(subprocess.Popen(
                    [str(compiler), "__run-tool", str(os.getpid()), sys.executable,
                     "-c", code, str(index)], cwd=root, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, start_new_session=os.name != "nt"))
            deadline = time.monotonic() + 30
            while len(list(root.glob("ready-*"))) != len(processes):
                for process in processes:
                    if process.poll() is not None:
                        output, error = process.communicate(timeout=10)
                        raise AssertionError(f"supervisor exited before barrier: {output}{error}")
                if time.monotonic() >= deadline:
                    raise AssertionError("guarded tools did not reach the barrier")
                time.sleep(.005)
            release.write_text("release")
            for index, process in enumerate(processes):
                output, error = process.communicate(timeout=30)
                assert process.returncode == (1 if index == 3 else 0), (index, output, error)
                if index == 3:
                    assert "error-3" in error, error
                    assert not any(f"error-{other}" in error for other in range(8) if other != 3), error
                else:
                    assert error == "", (index, error)
            for suffix, prefix in (("stdout", "output"), ("stderr", "error")):
                logs = list(root.glob(f"guarded-tool*.{suffix}"))
                assert len(logs) == 8, f"parallel supervisors shared {suffix}: {logs}"
                assert {path.read_text().strip() for path in logs} == {
                    f"{prefix}-{index}" for index in range(8)}, logs
        finally:
            release.write_text("release")
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=30)
    print("guarded tools: concurrent log ownership and failure diagnostics isolated")


if __name__ == "__main__":
    main()

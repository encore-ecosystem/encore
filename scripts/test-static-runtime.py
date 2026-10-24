#!/usr/bin/env python3
"""Exercise static publication and initialization cycles on the native host."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-static-") as scratch:
        binary = Path(scratch) / ("static-runtime.exe" if os.name == "nt" else "static-runtime")
        command = [args.cc, "-std=c11", "-O2", str(root / "packages/core/tests/static_runtime.c"),
                   "-o", str(binary)]
        if os.name != "nt":
            command.extend(["-pthread", "-lm"])
        subprocess.run(command, check=True, timeout=120)
        for mode, expected in ((None, 0), ("recursive", 1), ("cross-thread-cycle", 1)):
            result = subprocess.run([str(binary)] + ([mode] if mode else []),
                                    capture_output=True, text=True, timeout=20)
            print(json.dumps({"mode": mode or "24-readers", "exit_code": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr}), flush=True)
            if result.returncode != expected:
                raise SystemExit(f"unexpected static runtime result for {mode}")
            if mode and "cyclic static initialization" not in result.stderr:
                raise SystemExit(f"missing cycle diagnostic for {mode}")


if __name__ == "__main__":
    main()

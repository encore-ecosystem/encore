#!/usr/bin/env python3
"""Test compiler-native work queues and backend target isolation."""

import os
from pathlib import Path
import platform
import subprocess
import tempfile


def main():
    repository = Path(__file__).resolve().parents[1]
    backend = repository.parent / "encore-index/packages/ehir-llvm-backend/runtime.c"
    with tempfile.TemporaryDirectory(prefix="encore-build-runtime-") as directory:
        executable = Path(directory) / ("probe.exe" if os.name == "nt" else "probe")
        flags = [] if os.name == "nt" else ["-pthread"]
        subprocess.run([
            os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            *flags, str(repository / "tests/native/build_runtime.c"), str(backend),
            "-o", str(executable),
        ], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=30)
        identity = Path(directory) / ("identity.exe" if os.name == "nt" else "identity")
        subprocess.run([
            os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            str(repository / "tests/native/build_identity.c"), "-o", str(identity),
        ], check=True, timeout=60)
        subprocess.run([str(identity)], check=True, timeout=30)
    print(f"build runtime contracts passed on {platform.system()}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Check native RAM admission data and overflow-safe headroom calculations."""

import os
from pathlib import Path
import subprocess
import tempfile


def main():
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="encore-build-resources-") as directory:
        binary = Path(directory) / ("resources.exe" if os.name == "nt" else "resources")
        subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(repository / "tests/native/build_resources.c"), "-o", str(binary)],
                       check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)
    print("build resources: physical available RAM, strict kernel fields, overflow checks, 20% headroom passed")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise sharded profiler recording/report/reset on native CI runners."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--cc", default=os.environ.get("ENCORE_CC", "clang"))
parser.add_argument("--sanitizer", choices=("address", "thread"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="encore profile ") as temporary:
    binary = Path(temporary) / ("profile.exe" if os.name == "nt" else "profile")
    command = [args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
               str(root / "tests/profile_native.c"), "-o", str(binary)]
    if os.name != "nt":
        command.append("-pthread")
    if args.sanitizer:
        command += ["-g", "-fno-omit-frame-pointer", "-fsanitize=" + args.sanitizer]
    subprocess.run(command, check=True)
    subprocess.run([str(binary)], check=True, timeout=120)

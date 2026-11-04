#!/usr/bin/env python3
"""Exercise actual SDK native headers under AddressSanitizer on POSIX hosts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default=os.environ.get("CC", "clang"))
    parser.add_argument("--sanitizer", choices=("address", "thread", "none"), default="address")
    args = parser.parse_args()
    if platform.system() == "Windows":
        print("POSIX race harness is unavailable on Windows")
        return 0
    root = Path(__file__).resolve().parent.parent
    output = root / "target" / "native-sync-tests" / args.sanitizer
    output.mkdir(parents=True, exist_ok=True)
    cases = ("owned_waker", "sync_atomic_cancel", "sync_clock", "sync_channel", "sync_mutex", "sync_watch", "sync_signal", "sync_group")
    for case in cases:
        command = [args.compiler, "-O1", "-g", "-fno-omit-frame-pointer", "-pthread"]
        if args.sanitizer != "none":
            command.append("-fsanitize=" + args.sanitizer)
        binary = output / case
        command += [str(root / "tests" / "native" / (case + ".c")), "-o", str(binary)]
        subprocess.run(command, check=True, cwd=root)
        subprocess.run([str(binary)], check=True, timeout=60, cwd=root)
        print("passed:", case, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

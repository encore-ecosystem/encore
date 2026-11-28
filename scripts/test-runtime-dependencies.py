#!/usr/bin/env python3
"""Verify that basic SDK programs have no implicit networking dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = '''import std::io::println
import std::os::{argc, argv, write_file, read_file, file_sha256, remove_file}
fn background() -> u32 { ret 7_u32 }
fn main() -> u32 {
    if argc() < 1_usize || argv(0_usize).unwrap_or("") == "" { ret 1_u32 }
    let task = spawn background()
    if task.join() != 7_u32 { ret 2_u32 }
    if write_file("hash-fixture", "abc") != 0_i32 { ret 3_u32 }
    if read_file("hash-fixture") != "abc" { ret 4_u32 }
    if file_sha256("hash-fixture") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" { ret 5_u32 }
    let _removed = remove_file("hash-fixture")
    println("runtime-ok")
    ret 0_u32
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--profile", action="append", choices=("dev", "debug", "release", "extreme"))
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    readobj = shutil.which("llvm-readobj")
    driver = os.environ.get("ENCORE_CC") or shutil.which("clang")
    if not readobj and driver:
        sibling = Path(driver).parent / ("llvm-readobj.exe" if os.name == "nt" else "llvm-readobj")
        if sibling.is_file():
            readobj = str(sibling)
    readelf = shutil.which("readelf")
    if sys.platform != "darwin" and not readobj and not (os.name != "nt" and readelf):
        parser.error("llvm-readobj or readelf is required to inspect native dependencies")
    with tempfile.TemporaryDirectory(prefix="encore-runtime-") as temporary:
        root = Path(temporary)
        (root / "src").mkdir()
        (root / "src/main.enq").write_text(SOURCE)
        (root / "encore.toml").write_text('[project]\nname="runtime_probe"\nversion="0.0.0"\ndependencies=["sys@std"]\n')
        for profile in args.profile or ("dev", "debug", "release", "extreme"):
            command = [str(compiler), "build", "--profile", profile, "--jobs", "2"]
            built = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600)
            if built.returncode:
                raise AssertionError(built.stdout + built.stderr)
            binary = root / "target" / profile / ("runtime_probe.exe" if os.name == "nt" else "runtime_probe")
            result = subprocess.run([str(binary)], cwd=root, check=True, capture_output=True, text=True, timeout=30)
            assert result.stdout == "runtime-ok\n", result.stdout
            if sys.platform == "darwin":
                inspector = ["otool", "-L"]
            elif readobj:
                inspector = [readobj, "--coff-imports" if os.name == "nt" else "--needed-libs"]
            else:
                inspector = [readelf, "-d"]
            dependencies = subprocess.check_output([*inspector, str(binary)], text=True)
            for unwanted in ("Security.framework", "CoreFoundation.framework", "Network.framework", "libssl", "libcrypto", "libcares", "ws2_32.dll", "secur32.dll", "crypt32.dll"):
                assert unwanted.lower() not in dependencies.lower(), (profile, unwanted, dependencies)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            built = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=600)
            if built.returncode:
                raise AssertionError(built.stdout + built.stderr)
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest, "warm build changed binary"
            print(json.dumps({"profile": profile, "dependencies": dependencies, "sha256": digest}), flush=True)


if __name__ == "__main__":
    main()

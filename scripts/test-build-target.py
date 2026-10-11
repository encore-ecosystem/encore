#!/usr/bin/env python3
"""Cross-check runtime ABI detection and deterministic PE links without SDKs."""

import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def pe_headers(path, gnu, machine):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 60)[0]
    assert data[pe:pe + 4] == b"PE\0\0", path
    actual_machine, sections, timestamp = struct.unpack_from("<HHI", data, pe + 4)
    assert actual_machine == machine, (path, actual_machine)
    if gnu:
        assert timestamp == 0, (path, "wall-clock PE timestamp", timestamp)
        return
    # /Brepro marks the image with IMAGE_DEBUG_TYPE_REPRO. Merely linking twice
    # within the same second would not detect a missing reproducibility flag.
    optional = pe + 24
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B
    debug_rva, debug_size = struct.unpack_from("<II", data, optional + 112 + 6 * 8)
    for index in range(sections):
        section = optional + optional_size + index * 40
        size, rva, _, offset = struct.unpack_from("<IIII", data, section + 8)
        if rva <= debug_rva < rva + size:
            debug = offset + debug_rva - rva
            assert any(struct.unpack_from("<I", data, debug + entry + 12)[0] == 16
                       for entry in range(0, debug_size, 28)), path
            return
    raise AssertionError(f"{path}: missing reproducible PE debug record")


def production_function(source, name):
    match = re.search(r"^(?:pub )?fn " + re.escape(name) + r"\(", source, re.MULTILINE)
    assert match, name
    opening = source.index("{", match.start())
    depth = 0
    for token in re.finditer(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}]', source[opening:], re.DOTALL):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():opening + token.end()]
    raise AssertionError(f"unclosed production function: {name}")


def encore_policy_probe(repository, compiler):
    # The binary's private build module is not part of src/lib.enq. Exercise
    # its exact source bodies without exporting an internal production API.
    source = (repository / "src/modes/build.enq").read_text()
    names = ("compiler_args", "append_profile_link_args", "append_tls_link_args",
             "target_tool_args", "append_target_features", "native_path", "native_explicit_target_contract",
             "native_windows_reproducible_link_contract")
    policy = ('import std::vec::Vec\n'
              'import refrain::target::{TargetSpec, Toolchain, host_target, parse_target, default_toolchain}\n')
    for name in names:
        policy += "\n" + ("#attr(test)\n" if name.endswith("_contract") else "") + production_function(source, name) + "\n"
    with tempfile.TemporaryDirectory(prefix="encore-native-policy-") as directory:
        root = Path(directory)
        (root / "src/policy").mkdir(parents=True)
        (root / "src/target").mkdir()
        shutil.copyfile(repository / "src/target/mod.enq", root / "src/target/mod.enq")
        (root / "src/lib.enq").write_text('pub import refrain::policy\n')
        (root / "src/policy/mod.enq").write_text(policy)
        standard = (repository.parent / "encore-index/packages/std").as_posix()
        (root / "encore.toml").write_text(
            '[project]\nname="policy_probe"\nversion="0.0.0"\n'
            f'dependencies=["path@{standard}"]\n')
        (root / "runtime.c").write_text(f'#include "{(repository / "runtime/build_target.h").as_posix()}"\n')
        subprocess.run([str(compiler), "test", "--filter", "native_", "--jobs", "2", "--report", "report.json"],
                       cwd=root, check=True, timeout=180)
        report = json.loads((root / "report.json").read_text())
        assert report["summary"]["passed"] == 2 and report["summary"]["failed"] == 0, report
    print("production native policy: explicit targets, stable compilation directory and all-profile Windows linker flags passed", flush=True)


def encore_cross_probe(repository, compiler, mingw):
    """Optional full Encore check using a verified Linux llvm-mingw toolchain."""
    with tempfile.TemporaryDirectory(prefix="encore-windows-target-") as directory:
        root = Path(directory)
        (root / "src/target").mkdir(parents=True)
        shutil.copyfile(repository / "src/target/mod.enq", root / "src/target/mod.enq")
        standard = (repository.parent / "encore-index/packages/std").as_posix()
        (root / "encore.toml").write_text(
            '[project]\nname="target_probe"\nversion="0.0.0"\n'
            f'dependencies=["path@{standard}"]\n')
        (root / "src/main.enq").write_text(
            'import refrain::target::{host_triple, host_target, parse_target, target_is_host}\n'
            'import std::io::println\n'
            'fn main() -> u32 { println(host_triple())\n'
            'ret if host_target().environment == "gnu" && target_is_host(parse_target("host")) { 0 } else { 1 } }\n')
        header = (repository / "runtime/build_target.h").as_posix()
        (root / "runtime.c").write_text(f'#include "{header}"\n')
        environment = {**os.environ, "ENCORE_CC": str(mingw / "bin/clang"),
                       "ENCORE_LINKER": str(mingw / "bin/clang"),
                       "ENCORE_AR": str(mingw / "bin/llvm-ar"),
                       "ENCORE_BUILD_CACHE": str(root / "cache"),
                       "ENCORE_TARGETS_DIR": str(root / "targets")}
        host_info = subprocess.check_output([str(compiler), "target", "show", "host"], text=True, timeout=30)
        host = re.search(r"^Target:\s+(\S+)", host_info, re.MULTILINE).group(1)
        abi = ".".join((repository / "VERSION").read_text().split("-", 1)[0].split(".")[:2])
        for triple, machine in (("x86_64-w64-windows-gnu", 0x8664), ("aarch64-w64-windows-gnu", 0xAA64)):
            kit = root / "targets" / abi / triple
            shutil.copytree(repository.parent / "encore-index/packages/platform", kit / "platform")
            (kit / "manifest.json").write_text(json.dumps(
                {"schema": 1, "abi": abi, "host": host, "target": triple}))
            for profile in ("dev", "extreme"):
                command = [str(compiler), "build", "--target", triple, "--profile", profile, "--jobs", "2"]
                binary = root / f"target/{triple}/{profile}/target_probe.exe"
                subprocess.run(command, cwd=root, env=environment, check=True, timeout=300)
                pe_headers(binary, True, machine)
                before = binary.read_bytes()
                # Only disposable fixture output is removed; preserve the CAS
                # to exercise the same hydration/relink that failed in CI.
                shutil.rmtree(root / "target")
                subprocess.run(command, cwd=root, env=environment, check=True, timeout=300)
                if binary.read_bytes() != before:
                    evidence_parent = repository / "target/refrain-compilation-verification"
                    evidence_parent.mkdir(parents=True, exist_ok=True)
                    evidence = Path(tempfile.mkdtemp(prefix="windows-link-failure-", dir=evidence_parent))
                    shutil.copytree(root, evidence / "fixture")
                    (evidence / "before.exe").write_bytes(before)
                    shutil.copyfile(binary, evidence / "after.exe")
                    raise AssertionError((triple, profile, "hydrated PE mismatch", str(evidence)))
            if triple.startswith("x86_64") and shutil.which("wine"):
                wine_environment = {**environment, "WINEPREFIX": str(root / "wine"), "WINEDEBUG": "-all"}
                result = subprocess.run(["wine", str(binary)], env=wine_environment,
                                        capture_output=True, text=True, timeout=90)
                assert result.returncode == 0 and result.stdout.strip() == triple, result
                print("Wine: compiled Encore host_triple identifies Windows GNU correctly", flush=True)
        print("Encore Windows GNU: x86-64/AArch64 dev/extreme builds and byte-identical CAS hydration passed", flush=True)


def main():
    repository = Path(__file__).resolve().parents[1]
    source = repository / "tests/native/build_target.c"
    compiler = os.environ.get("CC", "clang")
    targets = (("x86_64-unknown-linux-gnu", False, 0),
               ("x86_64-pc-windows-msvc", False, 0x8664),
               ("aarch64-pc-windows-msvc", False, 0xAA64),
               ("x86_64-w64-windows-gnu", True, 0x8664),
               ("aarch64-w64-windows-gnu", True, 0xAA64))
    with tempfile.TemporaryDirectory(prefix="encore-target-") as directory:
        root = Path(directory)
        for triple, gnu, machine in targets:
            flags = [compiler, "--target=" + triple, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2"]
            ir = root / (triple + ".ll")
            subprocess.run([*flags, "-S", "-emit-llvm", str(source), "-o", str(ir)],
                           check=True, timeout=60)
            body = re.search(r"define[^\n]*@entry\([^)]*\)[^{]*\{([^}]+)\}", ir.read_text())
            assert body and f"ret i32 {int(gnu)}" in body.group(1), ir.read_text()
            objects = []
            for ordinal in range(2):
                staging = root / f"{triple}-staging-{ordinal}"
                staging.mkdir()
                obj = staging / "runtime.obj"
                subprocess.run([*flags, "-flto=thin", "-fdebug-compilation-dir=.", "-c", str(source), "-o", str(obj)],
                               cwd=staging, check=True, timeout=60)
                objects.append(obj)
            assert objects[0].read_bytes() == objects[1].read_bytes(), (triple, "staging-dependent ThinLTO bitcode")
            if not machine:
                continue
            linker = (["-Wl,-e,entry", "-Wl,--subsystem,console", "-Wl,--no-insert-timestamp"] if gnu else
                      ["-Wl,/entry:entry", "-Wl,/subsystem:console", "-Wl,/nodefaultlib", "-Wl,/Brepro"])
            binaries = []
            for ordinal in range(2):
                binary = root / f"{triple}-{ordinal}.exe"
                subprocess.run([compiler, "--target=" + triple, "-fuse-ld=lld", "-nostdlib",
                                *linker, str(objects[ordinal]), "-o", str(binary)], check=True, timeout=60)
                pe_headers(binary, gnu, machine)
                binaries.append(binary.read_bytes())
            assert binaries[0] == binaries[1], triple
    print("native targets: Linux/MSVC/GNU runtime ABI, x86-64/AArch64 PE machine, "
          "staging-independent ThinLTO objects, reproducible timestamps/markers and byte-identical links passed")
    if len(sys.argv) > 1:
        assert len(sys.argv) in (2, 3), "usage: test-build-target.py [COMPILER [LLVM_MINGW_ROOT]]"
        compiler = Path(sys.argv[1]).resolve()
        encore_policy_probe(repository, compiler)
        if len(sys.argv) == 3:
            encore_cross_probe(repository, compiler, Path(sys.argv[2]).resolve())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise the real EHIR CLI, native object, library API and extension package."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "fn answer() -> u32 {\n$entry:\nvalue: u32 = capprim 42_u32\nret value: u32\n}\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--ehir", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=ROOT / "target/ehir-compiler/contracts")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "ENCORE_CORE_DIR": str(ROOT / "packages/core"),
                   "ENCORE_BUILD_CACHE": str(work / "cache")}
    if args.registry:
        environment["ENCORE_REGISTRY_CACHE"] = str(args.registry.resolve())
    checks = []

    def run(label, command, *, cwd=work, expected=0):
        result = subprocess.run([str(v) for v in command], cwd=cwd, env=environment,
                                capture_output=True, text=True, timeout=600)
        (work / (label + ".log")).write_text(result.stdout + result.stderr)
        assert result.returncode == expected, (label, result.returncode, result.stdout, result.stderr)
        checks.append(label)
        print(label, "ok", flush=True)
        return result

    ehir = args.ehir.resolve()
    assert run("help", [ehir, "--help"]).stdout.startswith("Usage: ehir")
    assert run("list-backends", [ehir, "--list-backends"]).stdout.strip() == "llvm"
    run("version", [ehir, "--version"])
    source = work / "input with spaces.ehir"
    source.write_text(SOURCE)
    llvm = work / "answer.ll"
    run("llvm-default", [ehir, source, "--emit", "llvm-ir", "-o", llvm])
    original = llvm.read_bytes()
    assert b"define i32 @answer" in original
    run("llvm-explicit", [ehir, source, "--backend", "llvm", "--emit", "llvm-ir", "-o", llvm])
    assert llvm.read_bytes() == original
    obj = work / "answer object.o"
    run("object", [ehir, source, "-o", obj])
    assert obj.read_bytes().startswith(b"\x7fELF"), "expected a real native ELF object"
    harness = work / "harness.c"
    harness.write_text("extern unsigned answer(void); int main(void) { return answer() != 42u; }\n")
    executable = work / "native-test"
    run("link-object", ["clang", harness, obj, "-o", executable])
    run("execute-object", [executable])
    run("unknown-backend", [ehir, source, "--backend", "missing"], expected=2)
    run("missing-option", [ehir, "--target"], expected=2)
    run("invalid-jobs", [ehir, source, "--jobs", "0"], expected=1)
    bad = work / "bad.ehir"
    for index, text in enumerate([
        "not a module",
        "fn broken() -> u32 {\n$entry:\nx: u32 = invalid\nret x: u32\n}\n",
        "fn broken(a: u32) -> bool {\n$entry:\nsame = ieq a, a\nret same\n}\n",
        "fn broken(a: u32) -> u64 {\n$entry:\nret a: u64\n}\n",
        "fn broken() -> u32 {\n$entry:\nret absent: u32\n}\n",
    ]):
        bad.write_text(text)
        result = run(f"parse-error-{index}", [ehir, bad], expected=1)
        assert "panic:" not in result.stderr and "ehir[" in result.stderr
    sentinel = obj.read_bytes()
    run("failed-tool-preserves-output", [ehir, source, "-o", obj, "--cc", str(work / "missing-clang")], expected=1)
    assert obj.read_bytes() == sentinel
    assert not list(work.glob("*.ehir-*")), "staging directories leaked"

    consumer = work / "consumer"
    (consumer / "src").mkdir(parents=True, exist_ok=True)
    (consumer / "encore.toml").write_text(
        '[project]\nname = "ehir_consumer"\nbinary-name = "library-client"\nversion = "0.0.0"\n'
        f'dependencies = ["path@{ROOT / "packages/ehir"}", "path@{ROOT / "tests/fixtures/ehir-backend"}"]\n')
    (consumer / "src/main.enq").write_text('''import ehirlib::{CompileOptions, compile_with_backend, parse_text}
import inspection_backend::InspectionBackend
struct Counter { value: u32 }
impl for Counter {
    pub fn read(self: Self) -> u32 { ret self.value + 1_u32 }
}
fn unchanged() -> u32 { ret 7_u32 }
fn changed() -> u32 { ret 41_u32 }
fn main() -> u32 {
    if unchanged() != 7_u32 { ret 8_u32 }
    let counter = Counter { 6_u32 }
    if counter.read() != 7_u32 { ret 9_u32 }
    if parse_text("bad", "not EHIR").is_ok() { ret 1_u32 }
    let source = "fn answer() -> u32 {\\n$entry:\\nvalue: u32 = capprim 42_u32\\nret value: u32\\n}\\n"
    let program = match parse_text("test", source) { Ok(value) => value Err(_) => { ret 2_u32 } }
    let options = CompileOptions { "inspection-target", 16_usize, "dev", 1_usize }
    match compile_with_backend(program, options, InspectionBackend {}) {
        Ok(output) => {
            if output.backend != "inspection" || output.modules.len() != 1_usize { ret 3_u32 }
        }
        Err(_) => { ret 4_u32 }
    }
    ret changed() - 41_u32
}
''')
    run("library-consumer", [args.compiler.resolve(), "build", "--timings"], cwd=consumer)
    run("library-consumer-execution", [consumer / "target/dev/library-client"])
    main_source = consumer / "src/main.enq"
    main_source.write_text(main_source.read_text().replace("fn changed() -> u32 { ret 41_u32 }",
                                                          "fn changed() -> u32 { ret 42_u32 }"))
    run("incremental-library-consumer", [args.compiler.resolve(), "build", "--timings"], cwd=consumer)
    run("incremental-library-execution", [consumer / "target/dev/library-client"], expected=1)
    units = json.loads((consumer / "target/dev/encore-timings.json").read_text())["units"]
    phases = next(unit["phases"] for unit in units if unit["unit"] == "ehir_consumer")
    assert phases["prepared_functions_checked"] == 1, phases
    assert phases["prepared_functions_reused"] == 3, phases
    main_source.write_text(main_source.read_text().replace("ret self.value + 1_u32",
                                                          "ret self.value + 2_u32"))
    run("incremental-method-consumer", [args.compiler.resolve(), "build", "--timings"], cwd=consumer)
    run("incremental-method-execution", [consumer / "target/dev/library-client"], expected=9)
    units = json.loads((consumer / "target/dev/encore-timings.json").read_text())["units"]
    phases = next(unit["phases"] for unit in units if unit["unit"] == "ehir_consumer")
    assert phases["prepared_functions_checked"] == 1, phases
    assert phases["prepared_functions_reused"] == 3, phases
    main_source.write_text(main_source.read_text().replace("fn read(", "fn read_after_edit(")
                          .replace("counter.read()", "counter.read_after_edit()"))
    run("renamed-method-consumer", [args.compiler.resolve(), "build", "--timings"], cwd=consumer)
    run("renamed-method-execution", [consumer / "target/dev/library-client"], expected=9)
    units = json.loads((consumer / "target/dev/encore-timings.json").read_text())["units"]
    phases = next(unit["phases"] for unit in units if unit["unit"] == "ehir_consumer")
    assert phases["prepared_functions_checked"] == 2, phases
    assert phases["prepared_functions_reused"] == 2, phases
    fixture = ROOT / "tests/fixtures/ehir-backend"
    run("independent-backend", [args.compiler.resolve(), "build", "--timings"], cwd=fixture)
    units = json.loads((fixture / "target/dev/encore-timings.json").read_text())["units"]
    assert all(u["unit"] not in {"ehirlib", "ehir_llvm_backend", "llvm"} for u in units)
    (work / "result.json").write_text(json.dumps({"passed": len(checks), "checks": checks}, indent=2) + "\n")
    print(f"{len(checks)} EHIR compiler contracts passed", flush=True)


if __name__ == "__main__":
    main()

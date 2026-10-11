#!/usr/bin/env python3
"""Compile real package-owned EHIR after unrelated types/order/path changes."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


GENERATOR = '''//! Exercises the actual package lowering and LLVM backend together.
import core::option::Option
import std::vec::Vec
import std::os::{write_file, read_file}
import std::path::Path
import std::io::eprintln
import std::process::exit
import refrain::frontend::lexer::Lexer
import refrain::frontend::parser::{Parser, Statement}
import refrain::frontend::translator::{TranslationModule, translate_compilation_unit_to_ehir_chunks, assemble_ehir_module_bundle}
import refrain::target::host_target
import refrain::modes::build_archive::{UnitNativePlan, emit_package_archive}
import ehirlib::{parse_module_bundle_text, module_bundle_to_string}
import ehirlib::core::{make_module_bundle, Module}
import ehir_llvm_backend::codegen::{prepare_unit_codegen, emit_unit_codegen,
    unit_codegen_context, unit_codegen_requirements, emit_program_support, CodegenRequirements}

fn module(id: str, path: str, source: str) -> TranslationModule {
    let mut lexer = Lexer::new()
    let mut parser = Parser::new_for_source(path)
    let ast = match parser.parse_result(lexer.tokenize(source)) {
        Ok(value) => value
        Err(failure) => {
            let _ = eprintln("Invalid ABI fixture: " + source)
            let _ = exit(1)
            ret TranslationModule::new(id, path, Vec[str]::new(), Vec[Statement]::new(), Vec[str]::new())
        }
    }
    ret TranslationModule::new(id, path, Vec[str]::new(), ast, Vec[str]::new())
}

fn render(source: str, path: str, extra: bool, reversed: bool) -> str {
    let own = module("sample@lib.enq", path, source)
    let unrelated = module("unrelated@lib.enq", "/unrelated/src/lib.enq", "pub struct Value { wider: u64 }\\npub struct Other { n: u16 }\\npub trait Score { fn unrelated(self: Self) -> u64 }\\n")
    let mut modules = Vec[TranslationModule]::new()
    let mut selected = Vec[usize]::new()
    if reversed && extra { modules.push(unrelated) }
    modules.push(own)
    selected.push(if reversed && extra { 1_usize } else { 0_usize })
    if !reversed && extra { modules.push(unrelated) }
    let chunks = translate_compilation_unit_to_ehir_chunks(modules, host_target(), selected)
    ret assemble_ehir_module_bundle(chunks, modules.len(), "sample@lib.enq")
}

fn verify(source: str, name: str) -> bool {
    let first = render(source, "/one/src/lib.enq", false, false)
    if first != render(source, "/two/src/lib.enq", true, false)
        || first != render(source, "/three/src/lib.enq", true, true) { ret false }
    if write_file(name + ".ehir", first) != 0 { ret false }
    let target = host_target()
    let owned = parse_module_bundle_text("sample", first)
    let empty = make_module_bundle("", Vec[Module]::new())
    let prepared = prepare_unit_codegen(owned, empty, target.triple, target.pointer_width, 1)
    let modules = emit_unit_codegen(prepared, target.triple, target.pointer_width)
    if modules.len() != 1 { ret false }
    for emitted in modules { if write_file(name + ".unit.ll", emitted.ir) != 0 { ret false } }
    let context = unit_codegen_context(prepared, "sample")
    if write_file(name + ".ertemplate", module_bundle_to_string(context)) != 0 { ret false }
    let mut requirements = Vec[CodegenRequirements]::new()
    requirements.push(unit_codegen_requirements(prepared))
    let support = emit_program_support(context, requirements, target.triple, target.pointer_width)
    if write_file(name + ".support.ll", support.ir) != 0 { ret false }
    ret true
}

fn verify_dependency(producer_source: str, consumer_source: str) -> bool {
    let producer = module("producer@lib.enq", "/producer/src/lib.enq", producer_source)
    let mut consumer = module("consumer@main.enq", "/consumer/src/main.enq", consumer_source)
    consumer.imports.push("producer@lib.enq")
    let mut modules = Vec[TranslationModule]::new()
    modules.push(producer)
    modules.push(consumer)
    let mut producer_indices = Vec[usize]::new()
    producer_indices.push(0)
    let mut consumer_indices = Vec[usize]::new()
    consumer_indices.push(1)
    let target = host_target()
    let producer_text = assemble_ehir_module_bundle(
        translate_compilation_unit_to_ehir_chunks(modules, target, producer_indices), 2, "producer@lib.enq")
    let consumer_text = assemble_ehir_module_bundle(
        translate_compilation_unit_to_ehir_chunks(modules, target, consumer_indices), 2, "consumer@main.enq")
    let producer_unit = prepare_unit_codegen(parse_module_bundle_text("producer", producer_text),
        make_module_bundle("", Vec[Module]::new()), target.triple, target.pointer_width, 1)
    let producer_context = unit_codegen_context(producer_unit, "producer")
    // Exercise the actual persisted template boundary, rather than passing
    // ordinary producer bodies to the consumer's backend preparation.
    let dependency = parse_module_bundle_text("producer", module_bundle_to_string(producer_context))
    let consumer_unit = prepare_unit_codegen(parse_module_bundle_text("consumer", consumer_text),
        dependency, target.triple, target.pointer_width, 1)
    let mut native_args = Vec[str]::new()
    native_args.push("-O0")
    let plan = UnitNativePlan{read_file("native-compiler.txt"), read_file("native-archiver.txt"), native_args}
    if emit_package_archive(producer_unit, Path::new("target/producer-archive").resolve(), target, plan).is_err() {
        ret false
    }
    if emit_package_archive(consumer_unit, Path::new("target/consumer-archive").resolve(), target, plan).is_err() {
        ret false
    }
    for emitted in emit_unit_codegen(producer_unit, target.triple, target.pointer_width) {
        if write_file("dependency.producer.ll", emitted.ir) != 0 { ret false }
    }
    for emitted in emit_unit_codegen(consumer_unit, target.triple, target.pointer_width) {
        if write_file("dependency.consumer.ll", emitted.ir) != 0 { ret false }
    }
    let consumer_context = unit_codegen_context(consumer_unit, "consumer")
    let mut contexts = Vec[Module]::new()
    contexts.extend(producer_context.modules)
    contexts.extend(consumer_context.modules)
    let mut requirements = Vec[CodegenRequirements]::new()
    requirements.push(unit_codegen_requirements(producer_unit))
    requirements.push(unit_codegen_requirements(consumer_unit))
    let support = emit_program_support(make_module_bundle("consumer", contexts), requirements,
        target.triple, target.pointer_width)
    ret write_file("dependency.support.ll", support.ir) == 0
}

fn main() -> u32 {
    __CASES__
    if !verify_dependency(read_file("producer.enq"), read_file("consumer.enq")) { ret 1 }
    ret 0
}
'''


def main():
    repository = Path(__file__).resolve().parents[1]
    compiler = Path(sys.argv[1]).resolve()
    cases = {
        "embedded": "pub struct Value { n: u32 }\n"
                    "fn main() -> u32 { let original = Value{7}\n"
                    "unsafe { unsafe ehir { copied: Value = alias original: Value }\n"
                    "ret if copied.n == 7 { 0 } else { 1 } } }\n",
        "nominal": "pub struct Value { n: u32 }\n"
                   "impl for Value { pub fn read(self: Self) -> u32 { ret self.n } }\n"
                   "pub fn create(n: u32) -> Value { ret Value{n} }\n"
                   "fn main() -> u32 { ret if create(7).read() == 7 { 0 } else { 1 } }\n",
        "generic": "pub struct Value[T] { n: T }\n"
                   "impl[T] for Value[T] { pub fn read(self: Self) -> T { ret self.n } }\n"
                   "pub fn identity[T](value: T) -> T { ret value }\n"
                   "fn main() -> u32 { let item = identity(Value[u32]{7}) ret if item.read() == 7 { 0 } else { 1 } }\n",
        "generic_shadow": "pub struct T { n: u32 }\n"
                          "pub struct Value[T] { n: T }\n"
                          "impl[T] for Value[T] { pub fn read(self: Self) -> T { ret self.n } }\n"
                          "pub fn identity[T](value: T) -> T { ret value }\n"
                          "pub fn nominal(value: T) -> u32 { ret value.n }\n"
                          "fn main() -> u32 { let item = identity(Value[u32]{7}) let original = T{7} let direct = nominal(original) "
                          "ret if item.read() == 7 && direct == 7 { 0 } else { 1 } }\n",
        "enum_member_shadow": "pub struct String { n: u32 }\n"
                              "pub enum Json { String(u32), Empty }\n"
                              "pub fn field(value: Json) -> u32 { ret match value { Json::String(n) => n Json::Empty => 0_u32 } }\n"
                              "fn main() -> u32 { ret if field(Json::String(7_u32)) == 7_u32 { 0_u32 } else { 1_u32 } }\n",
        "trait": "pub trait Score { fn read(self: Self) -> u32 }\n"
                 "pub struct Value { n: u32 }\n"
                 "impl Score for Value { fn read(self: Value) -> u32 { ret self.n } }\n"
                 "fn use_trait(value: dyn Score) -> u32 { ret value.read() }\n"
                 "fn main() -> u32 { let value = Value{7} as dyn Score ret if use_trait(value) == 7 { 0 } else { 1 } }\n",
        "bound": "pub trait Score { fn read(self: Self) -> u32 }\n"
                 "pub struct Value { n: u32 }\n"
                 "impl Score for Value { fn read(self: Value) -> u32 { ret self.n } }\n"
                 "fn use_bound[T: Score](value: T) -> u32 { ret value.read() }\n"
                 "fn main() -> u32 { let value = Value{7} ret if use_bound(value) == 7 { 0 } else { 1 } }\n",
        "closure": "pub trait Handler { fn handle(self: Self, value: u32) -> u32 }\n"
                   "pub fn capture(base: u32) -> dyn Handler { ret |value| base + value }\n"
                   "fn main() -> u32 { let handler = capture(5) ret if handler.handle(2) == 7 { 0 } else { 1 } }\n",
        "decorator": (repository / "tests/decorator_method_chain.enq").read_text(encoding="utf-8"),
    }
    with tempfile.TemporaryDirectory(prefix="encore-unit-abi-") as directory:
        root = Path(directory) / "fixture with spaces"
        shutil.copytree(repository / "src", root / "src")
        calls = "\n".join("if !verify(read_file(" + json.dumps(name + ".enq") + "), " + json.dumps(name) + ") { ret 1 }"
                          for name, source in cases.items())
        for name, source in cases.items():
            (root / (name + ".enq")).write_text(source, encoding="utf-8")
        native_compiler = shutil.which(os.environ.get("CC", "clang"))
        native_archiver = shutil.which(os.environ.get("ENCORE_AR", "llvm-ar"))
        assert native_compiler and native_archiver, "native Clang/ar toolchain is unavailable"
        (root / "native-compiler.txt").write_text(str(Path(native_compiler).resolve()), encoding="utf-8")
        (root / "native-archiver.txt").write_text(str(Path(native_archiver).resolve()), encoding="utf-8")
        (root / "producer.enq").write_text(
            "pub struct Value { n: u32 }\n"
            "fn private_identity[T](value: T) -> T { ret value }\n"
            "pub fn identity[T](value: T) -> T { ret private_identity(value) }\n"
            "pub fn create(n: u32) -> Value { ret Value{n} }\n"
            "pub fn read(value: Value) -> u32 { ret value.n }\n", encoding="utf-8")
        (root / "consumer.enq").write_text(
            "import producer::{create, read, identity}\n"
            "fn main() -> u32 { let value = identity(create(7)) ret if read(value) == 7 { 0 } else { 1 } }\n",
            encoding="utf-8")
        (root / "src/main.enq").write_text(GENERATOR.replace("__CASES__", calls), encoding="utf-8")
        manifest = (repository / "encore.toml").read_text(encoding="utf-8")
        manifest = re.sub(r'"path@([^"\n]+)"', lambda match:
                          '"path@' + (repository / match.group(1)).resolve().as_posix() + '"', manifest)
        (root / "encore.toml").write_text(manifest, encoding="utf-8")
        runtime = (repository / "runtime.c").as_posix().replace('"', '\\"')
        (root / "runtime.c").write_text(f'#include "{runtime}"\n', encoding="utf-8")
        environment = {**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")}
        try:
            subprocess.run([str(compiler), "build", "--jobs", "2"], cwd=root, env=environment, check=True, timeout=600)
            generator = root / "target/dev" / ("encore.exe" if os.name == "nt" else "encore")
            subprocess.run([str(generator)], cwd=root, check=True, timeout=120)
            for name in cases:
                output = root / (name + (".exe" if os.name == "nt" else ".bin"))
                unit = root / (name + ".unit.ll")
                support = root / (name + ".support.ll")
                triple = re.search(r'^target triple = "([^"\n]+)"', unit.read_text(), re.M)
                assert triple, "backend omitted its target triple"
                assert not re.search(r"^define\b.*@__(?:drop|retain|add_edges|remove_edges)_", unit.read_text(), re.M), \
                    "package CGU contains program-wide ownership definitions"
                subprocess.run([os.environ.get("CC", "clang"), "--target=" + triple.group(1), "-O0", str(unit), str(support),
                                str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                               cwd=root, check=True, timeout=60)
                subprocess.run([str(output)], cwd=root, check=True, timeout=10)
            producer = root / "dependency.producer.ll"
            consumer = root / "dependency.consumer.ll"
            support = root / "dependency.support.ll"
            output = root / ("dependency.exe" if os.name == "nt" else "dependency.bin")
            triple = re.search(r'^target triple = "([^"\n]+)"', consumer.read_text(), re.M)
            assert triple
            for unit in (producer, consumer):
                assert not re.search(r"^define\b.*@__(?:drop|retain|add_edges|remove_edges)_",
                                     unit.read_text(), re.M), "dependency CGU owns program support"
            subprocess.run([os.environ.get("CC", "clang"), "--target=" + triple.group(1), "-O0",
                            str(producer), str(consumer), str(support),
                            str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                           cwd=root, check=True, timeout=60)
            subprocess.run([str(output)], cwd=root, check=True, timeout=10)
            archives = [root / "target/consumer-archive/unit.erlib", root / "target/producer-archive/unit.erlib"]
            for archive in archives:
                assert archive.read_bytes().startswith(b"!<arch>\n"), "unit output is not a real native archive"
            archive_output = root / ("archives.exe" if os.name == "nt" else "archives.bin")
            subprocess.run([native_compiler, "--target=" + triple.group(1), "-O0", str(support),
                            *(str(archive) for archive in archives),
                            str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(archive_output)],
                           cwd=root, check=True, timeout=60)
            subprocess.run([str(archive_output)], cwd=root, check=True, timeout=10)
            original_archives = [archive.read_bytes() for archive in archives]
            subprocess.run([str(generator)], cwd=root, check=True, timeout=120)
            assert original_archives == [archive.read_bytes() for archive in archives], "native archives are not deterministic"
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            parent = repository / "target/refrain-compilation-verification"
            parent.mkdir(parents=True, exist_ok=True)
            evidence = Path(tempfile.mkdtemp(prefix="abi-failure-", dir=parent))
            shutil.copytree(root, evidence / "fixture")
            print(f"ABI failure evidence: {evidence}", file=sys.stderr)
            raise
    print("package ABI: nominal/generic/dyn traits/bounds/closures/decorators and separately emitted producer/consumer with private generic templates, linked and executed")


if __name__ == "__main__":
    main()

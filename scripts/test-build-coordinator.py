#!/usr/bin/env python3
"""Compile eight real dependency packages in separate guarded compiler processes."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


DRIVER = '''//! Runs the real package coordinator and its private IPC workers.
import argparse::process_arg
import core::option::Option
import core::result::Result
import json::{Json, stringify}
import std::io::eprintln
import std::os::{read_file, write_file}
import std::path::Path
import std::vec::Vec
import refrain::project::build_graph::decode_build_graph
import refrain::target::host_target
import refrain::modes::build_coordinator::{compile_cached_package_graph, CompiledPackage}
import refrain::modes::build_artifacts::UnitReady
import refrain::modes::build_metadata::MetadataContext
import refrain::modes::build_worker::run_package_worker
import refrain::modes::build_archive::UnitNativePlan
import refrain::modes::build_requirements::UnitRequirements
import ehirlib::{parse_module_bundle_text, Module}
import ehirlib::core::make_module_bundle
import ehir_llvm_backend::codegen::{CodegenRequirements, emit_program_support}

fn exercise(jobs: usize, output: str) -> Result[bool, str] {
    let graph = decode_build_graph(read_file("graph.json"))?
    let plan = UnitNativePlan::decode(read_file("native.json"))?
    let target = host_target()
    let staging = Path::new(output).resolve()
    let packages = compile_cached_package_graph(graph, target.triple, "dev", jobs, 6442450944, staging, plan,
        Option[Path]::Some(Path::new("target/package-cache").resolve()))?
    let mut contexts = Vec[Module]::new()
    let mut requirements = Vec[CodegenRequirements]::new()
    let mut archives = Vec[Json]::new()
    for package in packages {
        let bundle = parse_module_bundle_text("", read_file(package.directory.join("unit.ertemplate").as_str()))
        contexts.extend(bundle.modules)
        requirements.push(UnitRequirements::decode(read_file(package.directory.join("unit.errequirements").as_str()),
            package.ready.context)?.requirements)
        archives.push(Json::String(package.directory.join("unit.erlib").as_str()))
    }
    let support = emit_program_support(make_module_bundle("consumer", contexts), requirements,
        target.triple, target.pointer_width)
    if write_file(staging.join("support.ll").as_str(), support.ir) != 0 ||
        write_file(staging.join("archives.json").as_str(), stringify(Json::Array(archives))) != 0 {
        ret Result[bool, str]::Err("cannot write final link inputs")
    }
    ret Result[bool, str]::Ok(true)
}

fn main() -> u32 {
    if process_arg(1).unwrap_or("") == "__compile-unit" { ret run_package_worker() }
    if process_arg(1).unwrap_or("") == "once" {
        match exercise(2, process_arg(2).unwrap_or("target/once")) {
            Ok(_) => { ret 0 }
            Err(error) => { eprintln(error) ret 1 }
        }
    }
    let mut budgets = Vec[usize]::new()
    budgets.push(1) budgets.push(2) budgets.push(4) budgets.push(8)
    for jobs in budgets {
        let output = f"target/graph-{jobs}"
        match exercise(jobs, output) {
            Ok(_) => {}
            Err(error) => { eprintln(error) ret 1 }
        }
    }
    ret 0
}
'''


def main():
    repository = Path(__file__).resolve().parents[1]
    compiler = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="encore-coordinator-") as directory:
        root = Path(directory) / "fixture with spaces"
        shutil.copytree(repository / "src", root / "src")
        (root / "src/main.enq").write_text(DRIVER, encoding="utf-8")
        manifest = (repository / "encore.toml").read_text()
        manifest = re.sub(r'"path@([^"\n]+)"', lambda item:
                          '"path@' + (repository / item.group(1)).resolve().as_posix() + '"', manifest)
        (root / "encore.toml").write_text(manifest)
        (root / "runtime.c").write_text('#include "' + (repository / "runtime.c").as_posix() + '"\n')
        cc = shutil.which(os.environ.get("CC", "clang"))
        ar = shutil.which(os.environ.get("ENCORE_AR", "llvm-ar"))
        assert cc and ar
        # The Encore encoder adds/verifies its native content identity.
        (root / "native-compiler.txt").write_text(str(Path(cc).resolve()))
        (root / "native-archiver.txt").write_text(str(Path(ar).resolve()))
        # Encode with the actual implementation, not a Python approximation.
        driver = DRIVER.replace('let plan = UnitNativePlan::decode(read_file("native.json"))?',
                                'let mut flags = Vec[str]::new()\n    flags.push("-O0")\n'
                                '    let extra = read_file("native-extra.txt")\n    if extra != "" { flags.push(extra) }\n'
                                '    let original = UnitNativePlan{read_file("native-compiler.txt"), read_file("native-archiver.txt"), flags}\n'
                                '    let plan = UnitNativePlan::decode(original.encode()?)?')
        (root / "src/main.enq").write_text(driver)
        packages = []

        def package(name, source, dependencies, binary=False):
            path = root / "packages" / name
            (path / "src").mkdir(parents=True)
            text = f'[project]\nname="{name}"\nversion="0.0.0"\ndependencies=[]\n'
            (path / "encore.toml").write_text(text)
            (path / "src" / ("main.enq" if binary else "lib.enq")).write_text(source)
            return {"name": name, "root": str(path), "distribution": str(path), "source": "fixture@" + name,
                    "binary": binary, "manifest": text, "dependencies": dependencies, "features": []}

        imports, calls = [], []
        for index in range(8):
            name = f"producer_{index}"
            packages.append(package(name,
                                    'fn private_identity[T](value: T) -> T { ret value }\n'
                                    'pub fn identity[T](value: T) -> T { ret private_identity(value) }\n'
                                    f'pub fn value() -> u32 {{ ret {index + 1} }}\n', []))
            imports.append(f"import {name}::{{value as value_{index}, identity as identity_{index}}}")
            calls.append(f"identity_{index}(value_{index}())")
        hidden = root / "packages/producer_0/src/hidden"
        hidden.mkdir()
        (hidden / "leaf.enq").write_text(
            'pub struct HiddenValue { value: u32 }\n'
            'impl for HiddenValue { pub fn read(self: Self) -> u32 { ret self.value } }\n')
        imports.append("import producer_0::hidden::leaf::HiddenValue")
        calls.append("HiddenValue{0}.read()")
        consumer = package("consumer", "\n".join(imports) + "\nfn main() -> u32 {\n    let sum = " +
                           " + ".join(calls) + "\n    ret if sum == 36 { 0 } else { 1 }\n}\n",
                           [item["name"] for item in packages], binary=True)
        (root / "graph.json").write_text(json.dumps({"schema": 1, "root": "consumer",
                                                    "features": [], "packages": [consumer, *packages]}))
        environment = {**os.environ, "ENCORE_CORE_DIR": str(repository.parent / "encore-index/packages/core")}
        try:
            subprocess.run([str(compiler), "build", "--jobs", "2"], cwd=root, env=environment,
                           check=True, timeout=900)
            executable = root / "target/dev" / ("encore.exe" if os.name == "nt" else "encore")
            subprocess.run([str(executable)], cwd=root, check=True, timeout=300)
            reference = None
            for jobs in (1, 2, 4, 8):
                staging = root / f"target/graph-{jobs}"
                workers = list(staging.glob("worker-*.stdout"))
                assert len(workers) == (9 if jobs == 1 else 0), (jobs, workers)
                archives = json.loads((staging / "archives.json").read_text())
                assert len(archives) == 9
                for path in archives:
                    assert Path(path).read_bytes().startswith(b"!<arch>\n")
                output = staging / ("program.exe" if os.name == "nt" else "program")
                support = staging / "support.ll"
                triple = re.search(r'^target triple = "([^"\n]+)"', support.read_text(), re.M)
                assert triple
                subprocess.run([cc, "--target=" + triple.group(1), "-O0", str(support), *archives,
                                str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                               cwd=root, check=True, timeout=60)
                subprocess.run([str(output)], cwd=root, check=True, timeout=10)
                signatures = [Path(path).read_bytes() for path in archives]
                if reference is None:
                    reference = signatures
                else:
                    assert reference == signatures, "package archives depend on jobs or staging paths"
            # Change only an ordinary dependency body. Consumers must hydrate,
            # while final linking takes the new archive rather than old code.
            producer = root / "packages/producer_0/src/lib.enq"
            producer.write_text(producer.read_text().replace("ret 1 }", "ret 2 }"))
            subprocess.run([str(executable), "once", "target/body-edit"], cwd=root, check=True, timeout=120)
            workers = list((root / "target/body-edit").glob("worker-*.stdout"))
            assert len(workers) == 1, workers
            archives = json.loads((root / "target/body-edit/archives.json").read_text())
            output = root / "target/body-edit/program"
            subprocess.run([cc, "-O0", str(root / "target/body-edit/support.ll"), *archives,
                            str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                           cwd=root, check=True, timeout=60)
            assert subprocess.run([str(output)], cwd=root, timeout=10).returncode == 1
            # A private generic-body edit changes templates, but not frontend
            # interfaces. Reprepare the consumer backend from its frontend
            # checkpoint using the new dependency template.
            producer.write_text(producer.read_text().replace("ret value }", "let next = value ret next }"))
            subprocess.run([str(executable), "once", "target/template-change"], cwd=root, check=True, timeout=180)
            assert len(list((root / "target/template-change").glob("worker-*.stdout"))) == 2
            consumer_phase = json.loads((root / "target/template-change/unit-0/phases.json").read_text())
            assert consumer_phase["frontend_cache_hit"] and not consumer_phase["backend_cache_hit"], consumer_phase
            archives = json.loads((root / "target/template-change/archives.json").read_text())
            output = root / "target/template-change/program"
            subprocess.run([cc, "-O0", str(root / "target/template-change/support.ll"), *archives,
                            str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                           cwd=root, check=True, timeout=60)
            assert subprocess.run([str(output)], cwd=root, timeout=10).returncode == 1
            # An archive checksum mismatch must cause reconstruction, not reuse.
            cache = root / "target/package-cache"
            current_consumer = Path(archives[0]).read_bytes()
            corrupt = next(path for path in cache.glob("*/unit.erlib") if path.read_bytes() == current_consumer)
            corrupt.write_bytes(b"broken")
            subprocess.run([str(executable), "once", "target/corrupt"], cwd=root, check=True, timeout=120)
            assert len(list((root / "target/corrupt").glob("worker-*.stdout"))) == 1
            # Different native flags invalidate ordinary archives, not the
            # already checked/lowered bodies. Exercise actual checkpoint decode.
            (root / "native-extra.txt").write_text("-g0")
            subprocess.run([str(executable), "once", "target/native-change"], cwd=root, check=True, timeout=180)
            assert len(list((root / "target/native-change").glob("worker-*.stdout"))) == 9
            phases = list((root / "target/native-change").glob("unit-*/phases.json"))
            assert len(phases) == 9
            assert all(json.loads(path.read_text())["backend_cache_hit"] for path in phases)
            archives = json.loads((root / "target/native-change/archives.json").read_text())
            output = root / "target/native-change/program"
            subprocess.run([cc, "-O0", str(root / "target/native-change/support.ll"), *archives,
                            str(repository.parent / "encore-index/packages/core/runtime.c"), "-o", str(output)],
                           cwd=root, check=True, timeout=60)
            assert subprocess.run([str(output)], cwd=root, timeout=10).returncode == 1
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, AssertionError):
            parent = repository / "target/refrain-compilation-verification"
            parent.mkdir(parents=True, exist_ok=True)
            evidence = Path(tempfile.mkdtemp(prefix="coordinator-failure-", dir=parent))
            shutil.copytree(root, evidence / "fixture")
            print(f"Coordinator failure evidence: {evidence}", file=sys.stderr)
            raise
    print("package coordinator: eight dependencies, isolated workers, verified cache hydration without workers, jobs=1/2/4/8, real archive link/run and byte parity passed")


if __name__ == "__main__":
    main()

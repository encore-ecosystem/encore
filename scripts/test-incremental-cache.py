#!/usr/bin/env python3
"""Exercise Encore's local and global incremental-cache invariants."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("compiler", type=Path)
    return parser.parse_args()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}"
        )
    return result


def build(compiler: Path, project: Path) -> str:
    return run(
        [str(compiler), "build", "--manifest-path", str(project / "encore.toml")],
        cwd=project,
    ).stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_ehir_state(project: Path, project_name: str) -> dict[str, tuple[str, str]]:
    path = project / "target" / "dev" / "ehir-cache" / "current.state"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(lines) < 2 or lines[0] != "encore-ehir-module-cache-v3":
        raise AssertionError(f"unexpected EHIR cache state: {lines[:2]}")
    if (len(lines) - 2) % 6:
        raise AssertionError("malformed EHIR cache state")
    records: dict[str, tuple[str, str]] = {}
    for index in range(2, len(lines), 6):
        module_id, _, _, _, chunk, digest = lines[index : index + 6]
        chunk_path = Path(chunk)
        if not chunk_path.is_file() or sha256(chunk_path) != digest:
            raise AssertionError(f"unverified EHIR chunk for {module_id}")
        records[module_id] = (chunk, digest)
    if not any(module_id.startswith(project_name + "@") for module_id in records):
        raise AssertionError(f"root module for {project_name} is absent")
    return records


def module_record(
    records: dict[str, tuple[str, str]], package: str
) -> tuple[str, str]:
    matches = [record for module_id, record in records.items() if module_id.startswith(package + "@")]
    if len(matches) != 1:
        raise AssertionError(f"expected one {package} module, got {len(matches)}")
    return matches[0]


def parse_llvm_state(project: Path, project_name: str) -> dict[str, tuple[Path, str]]:
    path = project / "target" / "dev" / f"{project_name}.ll.incremental-state"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(lines) < 2 or lines[0] != "encore-llvm-cgu-state-v2":
        raise AssertionError(f"unexpected LLVM cache state: {lines[:2]}")
    if (len(lines) - 2) % 4:
        raise AssertionError("malformed LLVM cache state")
    records: dict[str, tuple[Path, str]] = {}
    for index in range(2, len(lines), 4):
        module_id, _, artifact, digest = lines[index : index + 4]
        artifact_path = Path(artifact)
        if not artifact_path.is_file() or sha256(artifact_path) != digest:
            raise AssertionError(f"unverified LLVM module for {module_id}")
        sidecar = Path(str(artifact_path) + ".sha256")
        if sidecar.read_text(encoding="utf-8").strip() != digest:
            raise AssertionError(f"missing LLVM commit marker for {module_id}")
        records[module_id] = (artifact_path, digest)
    return records


def dependency_source(return_type: str, expression: str) -> str:
    return f"""pub fn cached_value() -> {return_type} {{
    {expression}
}}
"""


def create_fixture(root: Path, app_name: str, dependency_name: str) -> tuple[Path, Path]:
    dependency = root / "dependency"
    application = root / "application"
    write(
        dependency / "encore.toml",
        f'''[project]
name = "{dependency_name}"
version = "0.0.0"
description = "Incremental cache dependency"
readme = "README.md"
dependencies = []
''',
    )
    write(dependency / "README.md", "cache fixture\n")
    write(dependency / "src" / "lib.enq", dependency_source("u32", "ret 41_u32"))
    write(
        application / "encore.toml",
        f'''[project]
name = "{app_name}"
version = "0.0.0"
description = "Incremental cache application"
readme = "README.md"
dependencies = ["path@../dependency"]
''',
    )
    write(application / "README.md", "cache fixture\n")
    write(
        application / "src" / "main.enq",
        f"""import core::option::Option as Opt
import {dependency_name}::cached_value

fn checked_value() -> u64 {{
    let value = Opt[u64]::Some(cached_value() as u64)
    match value {{
        Opt[u64]::Some(found) => {{ ret found }}
        Opt[u64]::None => {{ ret 0_u64 }}
    }}
}}

fn main() -> u32 {{
    if checked_value() == 41_u64 {{ ret 0_u32 }}
    ret 1_u32
}}
""",
    )
    return application, dependency


def assert_binary_runs(application: Path, app_name: str) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    binary = application / "target" / "dev" / f"{app_name}{suffix}"
    run([str(binary)], cwd=application)


def main() -> int:
    args = parse_args()
    compiler = args.compiler.resolve()
    if not compiler.is_file():
        raise FileNotFoundError(compiler)

    with tempfile.TemporaryDirectory(prefix="encore-cache-regression-") as temporary:
        root = Path(temporary)
        token = hashlib.sha256(str(root).encode()).hexdigest()[:10]
        app_name = "cache_app_" + token
        dependency_name = "cache_dep_" + token
        application, dependency = create_fixture(root, app_name, dependency_name)

        build(compiler, application)
        assert_binary_runs(application, app_name)
        first = parse_ehir_state(application, app_name)

        second_output = build(compiler, application)
        second = parse_ehir_state(application, app_name)
        if first != second or "Finished" not in second_output:
            raise AssertionError("unchanged build did not preserve the complete EHIR cache")

        write(
            dependency / "src" / "lib.enq",
            dependency_source("u32", "let base = 40_u32\n    ret base + 1_u32"),
        )
        build(compiler, application)
        body_change = parse_ehir_state(application, app_name)
        if module_record(first, app_name) != module_record(body_change, app_name):
            raise AssertionError("private dependency-body edit rebuilt the consumer EHIR")
        if module_record(first, dependency_name) == module_record(body_change, dependency_name):
            raise AssertionError("dependency body edit reused stale EHIR")

        write(
            dependency / "src" / "lib.enq",
            dependency_source("u64", "ret 41_u64"),
        )
        build(compiler, application)
        interface_change = parse_ehir_state(application, app_name)
        if module_record(body_change, app_name) == module_record(interface_change, app_name):
            raise AssertionError("public dependency edit did not invalidate consumer EHIR")
        assert_binary_runs(application, app_name)

        expected_ehir = sha256(application / "target" / "dev" / f"{app_name}.ehir")
        shutil.rmtree(application / "target")
        build(compiler, application)
        hydrated = parse_ehir_state(application, app_name)
        if module_record(hydrated, app_name)[1] != module_record(interface_change, app_name)[1]:
            raise AssertionError("fresh target hydrated stale global EHIR")
        if sha256(application / "target" / "dev" / f"{app_name}.ehir") != expected_ehir:
            raise AssertionError("global-cache build differs from the local-cache build")
        assert_binary_runs(application, app_name)

        app_chunk = Path(module_record(hydrated, app_name)[0])
        app_chunk.write_text("corrupt EHIR cache entry\n", encoding="utf-8")
        write(
            dependency / "src" / "lib.enq",
            dependency_source("u64", "let base = 40_u64\n    ret base + 1_u64"),
        )
        build(compiler, application)
        repaired = parse_ehir_state(application, app_name)
        if sha256(Path(module_record(repaired, app_name)[0])) != module_record(repaired, app_name)[1]:
            raise AssertionError("corrupt EHIR chunk was not repaired")

        context = application / "target" / "dev" / f"{app_name}.ll.cgu-context.ehir"
        context.write_text("corrupt compact context\n", encoding="utf-8")
        write(dependency / "src" / "lib.enq", dependency_source("u64", "ret 41_u64"))
        build(compiler, application)
        if not context.is_file() or sha256(context) != Path(str(context) + ".sha256").read_text(
            encoding="utf-8"
        ).strip():
            raise AssertionError("corrupt compact EHIR context was not repaired")

        llvm = parse_llvm_state(application, app_name)
        app_llvm, _ = next(
            record for module_id, record in llvm.items() if module_id.startswith(app_name + "@")
        )
        app_llvm.write_text("corrupt LLVM cache entry\n", encoding="utf-8")
        write(
            dependency / "src" / "lib.enq",
            dependency_source("u64", "let answer = 41_u64\n    ret answer"),
        )
        build(compiler, application)
        parse_llvm_state(application, app_name)
        assert_binary_runs(application, app_name)

        llvm_manifest = application / "target" / "dev" / f"{app_name}.ll.modules"
        llvm_manifest.write_text("corrupt LLVM manifest\n", encoding="utf-8")
        write(dependency / "src" / "lib.enq", dependency_source("u64", "ret 41_u64"))
        build(compiler, application)
        parse_llvm_state(application, app_name)
        if sha256(llvm_manifest) != Path(str(llvm_manifest) + ".sha256").read_text(
            encoding="utf-8"
        ).strip():
            raise AssertionError("corrupt LLVM manifest was not repaired")

        llvm_state = application / "target" / "dev" / f"{app_name}.ll.incremental-state"
        llvm_state.write_text("corrupt LLVM state\n", encoding="utf-8")
        write(
            dependency / "src" / "lib.enq",
            dependency_source("u64", "let answer = 40_u64\n    ret answer + 1_u64"),
        )
        build(compiler, application)
        parse_llvm_state(application, app_name)
        if sha256(llvm_state) != Path(str(llvm_state) + ".sha256").read_text(
            encoding="utf-8"
        ).strip():
            raise AssertionError("corrupt LLVM state was not repaired")
        assert_binary_runs(application, app_name)

        clean_root = root / "clean"
        clean_application, clean_dependency = create_fixture(
            clean_root, app_name, dependency_name
        )
        write(
            clean_dependency / "src" / "lib.enq",
            (dependency / "src" / "lib.enq").read_text(encoding="utf-8"),
        )
        build(compiler, clean_application)
        clean_ehir = clean_application / "target" / "dev" / f"{app_name}.ehir"
        current_ehir = application / "target" / "dev" / f"{app_name}.ehir"
        if sha256(clean_ehir) != sha256(current_ehir):
            raise AssertionError("incremental output differs from a clean compilation")

    print("incremental cache regression passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, FileNotFoundError, OSError, RuntimeError) as error:
        print(f"error: {error}")
        raise SystemExit(1)

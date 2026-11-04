#!/usr/bin/env python3
"""Record cold, warm and incremental builds of a generated 463-endpoint SDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler-profile", default="unspecified", help="profile used to build the compiler executable")
    parser.add_argument("--endpoints", type=int, default=463)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.endpoints < 1 or args.repetitions < 1:
        parser.error("endpoint and repetition counts must be positive")
    compiler = args.compiler.resolve()
    repository = Path(__file__).resolve().parent.parent
    targets = subprocess.check_output([str(compiler), "target"], text=True)
    host = re.search(r"^Target:\s+(\S+)", targets, re.MULTILINE)
    if host is None:
        raise RuntimeError("compiler did not identify its native host target: " + targets)
    triple = host.group(1)
    report = {
        "schema": 1, "fixture": "generated-sdk-v1", "endpoints": args.endpoints,
        "compiler_sha256": digest(compiler), "compiler_profile": args.compiler_profile,
        "compiler_version": subprocess.check_output([str(compiler), "--version"], text=True).strip(),
        "platform": platform.platform(), "profile": "dev", "target": triple, "jobs": "automatic", "logical_cpus": os.cpu_count(),
        "cache_policy": "each repetition has a new private project/package cache; OS buffers and native tools retained",
        "samples": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="encore-sdk-benchmark-") as directory:
        for repetition in range(args.repetitions):
            root = Path(directory) / str(repetition)
            (root / "src").mkdir(parents=True)
            sdk = root / "sdk"
            (sdk / "src").mkdir(parents=True)
            (sdk / "encore.toml").write_text('[project]\nname="bench_sdk"\nversion="0.0.0"\ndependencies=[]\n')
            original = ''.join(f'pub struct Row{i} {{ value: u64 }}\npub fn endpoint_{i}(row: Row{i}) -> u64 {{ ret row.value + 1_u64 }}\n' for i in range(args.endpoints))
            original += 'pub fn identity[T](value: T) -> T { ret value }\npub fn unused[T](value: T) -> T { ret value }\n'
            library = sdk / "src/lib.enq"
            library.write_text(original)
            manifest = '[project]\nname="sdk_benchmark"\nversion="0.0.0"\ndependencies=["path@sdk"]\n'
            (root / "encore.toml").write_text(manifest)
            source = root / "src/main.enq"
            source.write_text('import bench_sdk::{Row0, endpoint_0, identity}\nfn main() -> u32 { let result = identity[u64](endpoint_0(Row0{41_u64}) as u64) ret if result == 42_u64 { 0_u32 } else { 1_u32 } }\n')
            (root / "runtime.c").write_text('#include <stdint.h>\nuint32_t benchmark_native(void) { return 42; }\n')
            env = dict(os.environ, ENCORE_CORE_DIR=str(repository / "packages/core"),
                       ENCORE_BUILD_CACHE=str(root / "cache"))

            def measure(case: str) -> None:
                inputs = sorted(p for folder in (root / "src", sdk) for p in folder.rglob("*") if p.is_file())
                inputs += [root / "encore.toml", root / "runtime.c"]
                fingerprint = hashlib.sha256()
                for path in sorted(inputs):
                    fingerprint.update(str(path.relative_to(root)).encode())
                    fingerprint.update(path.read_bytes())
                started = time.perf_counter()
                run = subprocess.run([str(compiler), "build", "--timings"], cwd=root, env=env, text=True, capture_output=True, timeout=600)
                elapsed = time.perf_counter() - started
                timing = root / "target/dev/encore-timings.json"
                sample = {"repetition": repetition, "case": case, "source_sha256": fingerprint.hexdigest(),
                          "wall_seconds": elapsed, "status": run.returncode,
                          "timings": json.loads(timing.read_text()) if timing.exists() else None}
                report["samples"].append(sample)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print(f"{repetition + 1} {case}: {elapsed:.3f}s status={run.returncode}", flush=True)
                if run.returncode:
                    raise RuntimeError(run.stdout + run.stderr)
                binary = root / "target/dev" / ("sdk_benchmark.exe" if os.name == "nt" else "sdk_benchmark")
                subprocess.run([str(binary)], check=True, timeout=10)
                if case == "warm" and not sample["timings"].get("input_cache_hit", sample["timings"].get("link_cache_hit", False)):
                    raise RuntimeError("unchanged build missed its input receipt")

            measure("cold")
            measure("warm")
            source.write_text(source.read_text().replace("let result =", "let calculated =").replace("if result ==", "if calculated =="))
            measure("application_body")
            library.write_text(library.read_text().replace("ret row.value + 1_u64", "let previous = row.value ret previous + 1_u64", 1))
            measure("dependency_body")
            library.write_text(library.read_text().replace("endpoint_0(row: Row0) -> u64", "endpoint_0(row: Row0) -> u32").replace("ret previous + 1_u64", "ret (previous + 1_u64) as u32", 1))
            measure("public_interface")
            library.write_text(library.read_text().replace("identity[T](value: T) -> T { ret value }", "identity[T](value: T) -> T { let same = value ret same }"))
            measure("reachable_generic")
            library.write_text(library.read_text().replace("unused[T](value: T) -> T { ret value }", "unused[T](value: T) -> T { let same = value ret same }"))
            measure("unreachable_generic")
            (root / "encore.toml").write_text(manifest + f'\n[target.{triple}]\ncompile-args=["-DBENCHMARK_NATIVE=1"]\n')
            measure("native_flags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify operator outputs, exact operand types and cached package contracts."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def verify(compiler: Path, root: Path) -> None:
    core = root / "core"
    ignored = shutil.ignore_patterns("target", ".encore", ".encore_cache", ".git", "__pycache__")
    shutil.copytree(ROOT / "packages/core", core, ignore=ignored)
    shutil.copytree(ROOT / "packages/platform", root / "platform", ignore=ignored)
    project = root / "app"
    (project / "src").mkdir(parents=True)
    (project / "encore.toml").write_text(
        '[project]\nname="operator_contracts"\nversion="0.0.0"\ndependencies='
        + json.dumps([f"path@{core.as_posix()}"]) + '\n', encoding="utf-8")
    source = project / "src/main.enq"
    positive = (ROOT / "tests/operator_contracts.enq").read_text(encoding="utf-8")
    env = dict(os.environ, ENCORE_CORE_DIR=str(core), ENCORE_BUILD_CACHE=str(root / "cache"),
               ENCORE_INDEX_URL="http://127.0.0.1:9/index")

    def run(*args: str, error: str | None = None) -> None:
        result = subprocess.run([str(compiler), *args], cwd=project, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=600)
        if error is None:
            if result.returncode == 0:
                return
        elif result.returncode != 0 and error in result.stdout + result.stderr:
            return
        raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")

    source.write_text(positive, encoding="utf-8")
    run("run", "--jobs", "1")
    run("run", "--jobs", "2")  # dependency metadata and warm caches retain Output
    for operator in ["+", "-", "*", "/", "%", "**", "&", "|", "^", "<<", ">>", "==", "!=", "<", "<=", ">", ">="]:
        source.write_text(f'fn main() -> u32 {{ let left = 1_u8 let right = 2_u16 let value = left {operator} right ret 0_u32 }}\n', encoding="utf-8")
        run("build", error="missing-operator-implementation")
        source.write_text(f'fn main() -> u32 {{ let value = 1_u8 {operator} 2_u16 ret 0_u32 }}\n', encoding="utf-8")
        run("build", error="missing-operator-implementation")
    source.write_text('''import core::ops::Add
struct Number { value: u32 }
impl Add[u32, u32] for Number { fn op(self: Self, other: u32) -> u32 { ret other } }
impl Add[u32, u64] for Number { fn op(self: Self, other: u32) -> u64 { ret other as u64 } }
fn main() -> u32 { let result = Number{1_u32} + 2_u32 ret 0_u32 }
''', encoding="utf-8")
    run("build", error="operator-implementation")
    print("operator SDK: exact operands, Output, generic dispatch, caches and diagnostics verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore-operator-contracts-") as directory:
        verify(args.compiler.resolve(), Path(directory))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify that the bridge can compile the next release's operator SDK."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OPERATORS = "Add Sub Mul Div Rem Pow BitAnd BitOr BitXor Shl Shr".split()


def next_operator_sdk(source: str) -> str:
    for name in OPERATORS:
        old = f"pub trait {name}[Rhs] {{\n    fn op(self: Self, other: Rhs) -> Self\n}}"
        new = f"pub trait {name}[Rhs, Output] {{\n    fn op(self: Self, other: Rhs) -> Output\n}}"
        if source.count(old) != 1:
            raise ValueError(f"expected one legacy {name} declaration")
        source = source.replace(old, new)
        source = re.sub(rf"impl {name}\[([^\[\]\n]+)\] for ([A-Za-z0-9_]+) {{",
                        lambda match: f"impl {name}[{match[1]}, {match[2]}] for {match[2]} {{", source)
    return source


def verify(compiler: Path, root: Path) -> None:
    core = root / "core"
    shutil.copytree(ROOT / "packages/core", core, ignore=shutil.ignore_patterns("target", ".encore"))
    ops = core / "src/ops/mod.enq"
    ops.write_text(next_operator_sdk(ops.read_text(encoding="utf-8")), encoding="utf-8")
    project = root / "app"
    (project / "src").mkdir(parents=True)
    (project / "encore.toml").write_text(
        '[project]\nname="operator_preview"\nversion="0.0.0"\ndependencies='
        + json.dumps([f"path@{core.as_posix()}"]) + '\n', encoding="utf-8")
    source = project / "src/main.enq"
    positive = (ROOT / "tests/fixtures/language_operators/main.enq").read_text(encoding="utf-8")
    env = dict(os.environ, ENCORE_CORE_DIR=str(core), ENCORE_BUILD_CACHE=str(root / "cache"),
               ENCORE_INDEX_URL="http://127.0.0.1:9/index")

    def run(*args: str, error: str | None = None) -> None:
        result = subprocess.run([str(compiler), *args], cwd=project, env=env,
                                capture_output=True, text=True, timeout=600)
        if error is None:
            if result.returncode == 0:
                return
        elif result.returncode != 0 and error in result.stdout + result.stderr:
            return
        raise AssertionError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")

    source.write_text(positive, encoding="utf-8")
    run("run", "--jobs", "1")
    run("run", "--jobs", "2")  # dependency metadata and warm caches retain Output
    source.write_text('fn main() -> u32 { let value = 1_u8 + 2_u16 ret 0_u32 }\n', encoding="utf-8")
    run("build", error="missing-operator-implementation")
    source.write_text('''import core::ops::Add
struct Number { value: u32 }
impl Add[u32, u32] for Number { fn op(self: Self, other: u32) -> u32 { ret other } }
impl Add[u32, u64] for Number { fn op(self: Self, other: u32) -> u64 { ret other as u64 } }
fn main() -> u32 { let result = Number{1_u32} + 2_u32 ret 0_u32 }
''', encoding="utf-8")
    run("build", error="operator-implementation")
    print("next-release operator SDK: exact operands, Output, generic dispatch, caches and diagnostics verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore-language-bridge-") as directory:
        verify(args.compiler.resolve(), Path(directory))


if __name__ == "__main__":
    main()

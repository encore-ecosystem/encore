#!/usr/bin/env python3
"""Compile and run colliding nominal types, including collection and method calls."""
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile


def main():
    compiler = str(Path(sys.argv[1] if len(sys.argv) > 1 else "target/dev/encore").resolve())
    with tempfile.TemporaryDirectory(prefix="encore-type-identity-") as scratch:
        root = Path(scratch)
        (root / "src").mkdir()
        (root / "encore.toml").write_text('[project]\nname="identity_probe"\nversion="0.0.0"\ndependencies=[]\n')
        for name, typ, value, constructor in (("left", "u32", "7_u32", "new()"),
                                                ("right", "str", '"ok"', "with_capacity(2_usize)")):
            (root / "src" / f"{name}.enq").write_text(f'''import core::ops::ContextManager
import core::vec::Vec
pub struct Connection {{ value: {typ} }}
impl for Connection {{
    pub fn new() -> Self {{ ret Self {{ {value} }} }}
    pub fn again() -> Self {{ ret Self::new() }}
    pub fn value(self: Self) -> {typ} {{ ret self.value }}
}}
impl ContextManager for Connection {{
    pub fn with_enter(self: Self) -> Self {{ ret self }}
    pub fn with_exit(self: Self) -> bool {{ ret true }}
}}
pub fn accept(values: Vec[Connection]) -> bool {{ ret values.len() == 1_usize }}
pub fn connection() -> Connection {{ ret Connection::again() }}
pub fn {name}_run() -> bool {{
    with Connection::again() as item {{
        if item.value() != {value} {{ ret false }}
        let mut values = Vec[Connection]::{constructor}
        values.push(item)
        ret accept(values)
    }}
}}
#attr(test)
fn same_named_test() -> bool {{ ret {name}_run() }}
''')
        entry = root / "src/main.enq"
        entry.write_text('import refrain::left::left_run\nimport refrain::right::right_run\nfn main() -> u32 { ret if left_run() && right_run() { 0_u32 } else { 1_u32 } }\n')
        environment = {**os.environ, "ENCORE_REGISTRY_CACHE": str(root / "registry-cache")}
        result = subprocess.run([compiler, "run"], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([compiler, "test", "--jobs", "2"], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0 and "2 passed" in result.stdout + result.stderr, result.stdout + result.stderr
        # Alternating workspaces share unchanged dependency sources but have
        # different collision sets. A fresh target must not hydrate chunks
        # whose nominal names were produced for the other graph.
        for fixture, collision in (("single-first", False), ("collision", True), ("single-again", False)):
            project = root / fixture
            project.mkdir()
            shutil.copy(root / "encore.toml", project / "encore.toml")
            shutil.copytree(root / "src", project / "src")
            if not collision:
                (project / "src/right.enq").unlink()
                (project / "src/main.enq").write_text('import refrain::left::left_run\nfn main() -> u32 { ret if left_run() { 0_u32 } else { 1_u32 } }\n')
            result = subprocess.run([compiler, "run"], cwd=project, env=environment,
                                    capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, fixture + "\n" + result.stdout + result.stderr
        entry.write_text('import refrain::left::accept\nimport refrain::right::{Connection, connection}\nimport core::vec::Vec\nfn main() -> u32 { let mut values = Vec[Connection]::new() values.push(connection()) let wrong = accept(values) ret 0_u32 }\n')
        result = subprocess.run([compiler, "build"], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=120)
        assert result.returncode != 0, "distinct nominal types must not become interchangeable"
        assert "argument-mismatch" in result.stdout + result.stderr, result.stdout + result.stderr
    print("Nominal identity: collections, static/instance methods, context managers and rejection passed")


if __name__ == "__main__":
    main()

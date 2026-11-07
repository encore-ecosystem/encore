#!/usr/bin/env python3
"""Require impossible Dict and Set capacities to panic promptly on native CI."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PANIC = "panic: Dict capacity overflow"
# Every native CI target has 64-bit usize.
MAX_CAPACITY = "18446744073709551615_usize"
CASES = {
    "dict_constructor": f'''import core::dict::Dict
fn main() -> u32 {{
    let values = Dict[u32, u32]::with_capacity({MAX_CAPACITY})
    ret values.len() as u32
}}
''',
    "set_constructor": f'''import core::set::Set
fn main() -> u32 {{
    let values = Set[u32]::with_capacity({MAX_CAPACITY})
    ret values.len() as u32
}}
''',
    "dict_reserve": f'''import core::dict::Dict
fn main() -> u32 {{
    let mut values = Dict[u32, u32]::new()
    values.insert(1_u32, 1_u32)
    values.reserve({MAX_CAPACITY})
    ret values.len() as u32
}}
''',
}


def run(command, project, environment, timeout, name):
    try:
        return subprocess.run(command, cwd=project, env=environment, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""

        raise SystemExit(f"{name} timed out after {timeout}s\n"
                         f"{text(error.stdout)}\n{text(error.stderr)}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    core = ROOT / "packages/core"
    with tempfile.TemporaryDirectory(prefix="encore-hash-capacity-") as directory:
        temporary = Path(directory)
        environment = dict(os.environ, ENCORE_CORE_DIR=str(core),
                           ENCORE_BUILD_CACHE=str(temporary / "cache"),
                           ENCORE_REGISTRY_CACHE=str(temporary / "registry"),
                           ENCORE_INDEX_URL="http://127.0.0.1:9/index")
        for name, source in CASES.items():
            project = temporary / name
            (project / "src").mkdir(parents=True)
            dependencies = json.dumps([f"path@{core.as_posix()}",
                                       f"path@{(ROOT / 'packages/platform').as_posix()}"])
            (project / "encore.toml").write_text(
                f'[project]\nname="{name}"\nversion="0.0.0"\ndependencies={dependencies}\n',
                encoding="utf-8", newline="\n")
            (project / "src/main.enq").write_text(source, encoding="utf-8", newline="\n")
            build = run([str(compiler), "build", "--profile", "dev", "--jobs", "2"],
                        project, environment, 600, name + " build")
            if build.returncode != 0:
                raise SystemExit(f"{name} build failed ({build.returncode})\n{build.stdout}\n{build.stderr}")
            binary = project / "target/dev" / (name + (".exe" if os.name == "nt" else ""))
            result = run([str(binary)], project, environment, 5, name)
            if result.returncode == 0 or PANIC not in result.stderr:
                raise SystemExit(f"{name}: expected nonzero exit and {PANIC!r}; got {result.returncode}\n"
                                 f"{result.stdout}\n{result.stderr}")
            print(f"{name}: capacity overflow panicked promptly", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a cold and warm application using only the extracted release SDK."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile


def verify(archive: Path, release: str, triple: str, scratch: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as stream:
            stream.extractall(scratch)
    else:
        with tarfile.open(archive, "r:gz") as stream:
            stream.extractall(scratch, filter="data")
    installation = scratch / f"encore-{release}-{triple}"
    executable = "encore.exe" if "-windows-" in triple else "encore"
    compiler = installation / "bin" / executable
    compiler.chmod(0o755)
    project = scratch / "application"
    (project / "src").mkdir(parents=True)
    sdk = installation / "lib/encore/index"
    dependencies = [f"path@{(sdk / name).as_posix()}" for name in ("std", "json")]
    (project / "encore.toml").write_text(
        '[project]\nname="installed_sdk_probe"\nversion="0.0.0"\ndependencies='
        + json.dumps(dependencies) + '\n', encoding="utf-8")
    (project / "src/main.enq").write_text('''import core::testing::assert
import std::io::println
import json::{Json, parse, stringify}
fn main() -> u32 {
    let value = parse("42").unwrap_or(Json::Null)
    if !assert(stringify(value) == "42") { ret 1_u32 }
    println("installed-sdk-ok")
    ret 0_u32
}
''', encoding="utf-8")
    env = dict(os.environ)
    for name in ("ENCORE_CORE_DIR", "ENCORE_HOME", "ENCORE_DEFAULT_INDEX"):
        env.pop(name, None)
    env.update(ENCORE_BUILD_CACHE=str(scratch / "compiled-cache"),
               ENCORE_REGISTRY_CACHE=str(scratch / "empty-registry"),
               ENCORE_INDEX_URL="http://127.0.0.1:9/index")
    for _ in range(2):
        result = subprocess.run([str(compiler), "run", "--jobs", "2"], cwd=project,
                                env=env, capture_output=True, text=True, timeout=600)
        if result.returncode != 0 or "installed-sdk-ok" not in result.stdout:
            raise AssertionError(f"installed SDK failed ({result.returncode})\n{result.stdout}\n{result.stderr}")
    print("extracted release SDK: cold and warm offline application verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--triple", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore installed SDK ") as directory:
        verify(args.archive.resolve(), args.release, args.triple, Path(directory))


if __name__ == "__main__":
    main()

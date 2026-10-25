#!/usr/bin/env python3
"""Compile project constants through package caches, generics and tooling."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def write(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")


def compiler_tests(compiler, temporary):
    root, dependency = temporary / "app", temporary / "dependency"
    env = dict(os.environ, ENCORE_CORE_DIR=str(ROOT / "packages/core"),
               ENCORE_BUILD_CACHE=str(temporary / "cache"), ENCORE_INDEX_URL="http://127.0.0.1:9/index")
    std = (ROOT / "packages/std").as_posix()

    def manifest(path, name, version):
        values = f'[project]\nname={json.dumps(name)}\n'
        if version is not None:
            values += f'version={json.dumps(version)}\n'
        # Regression #164: UTF-8 metadata must not shift dependency parsing.
        values += 'description="Quiet Day — demo"\n'
        dependencies = [f"path@{std}"]
        if path == root:
            dependencies.append(f"path@{dependency.as_posix()}")
        write(path / "encore.toml", values + 'dependencies=' + json.dumps(dependencies) + '\n')

    def run(*args, good=True):
        result = subprocess.run([compiler, *args], cwd=root, env=env, capture_output=True, timeout=240)
        if good:
            assert result.returncode == 0, (args, result.stdout, result.stderr)
        else:
            assert result.returncode != 0, (args, result.stdout, result.stderr)
        return result

    manifest(dependency, "metadata_dependency", "2.1.0")
    manifest(root, "metadata_app", "1.2.3")
    write(dependency / "src/lib.enq", '''pub fn identity() -> str {
    ret __project_name__ + "=" + __version__
}
pub fn generic_identity[T](_value: T) -> str {
    ret __project_name__ + "=" + __version__
}
pub struct Member { __version__: str }
impl for Member {
    pub fn __project_name__(self: Self) -> str { ret "method" }
}
pub enum Qualified { __version__ }
pub fn member() -> str {
    let value = Member { "member" }
    let _variant = Qualified::__version__
    ret value.__version__ + "/" + value.__project_name__()
}
''')
    source = '''import core::fmt::Debug
import std::io::println
import metadata_dependency::{identity, generic_identity, member}
macro_rules! version_value {
    () => (__version__);
}
fn main() -> u32 {
    println(__project_name__ + "=" + __version__)
    println(identity())
    println(generic_identity(1_u32))
    println(f"{__project_name__}/{__version__}")
    println(version_value!())
    println(member())
    println("__version__")
    ret 0_u32
}
#attr(test)
fn project_constants_have_string_type() -> bool {
    let version: str = __version__
    let name: str = __project_name__
    ret version.len() > 0_usize && name.len() > 0_usize
}
'''
    write(root / "src/main.enq", source)

    def expect(app="1.2.3", lib="2.1.0", name="metadata_app"):
        expected = f"{name}={app}\nmetadata_dependency={lib}\nmetadata_dependency={lib}\n{name}/{app}\n{app}\nmember/method\n__version__\n".encode()
        binary = root / "target/dev" / (name + (".exe" if os.name == "nt" else ""))
        result = subprocess.run([str(binary)], cwd=temporary, env=env, capture_output=True, timeout=15)
        assert result.returncode == 0 and result.stdout.replace(b"\r\n", b"\n") == expected, (result, expected)
        return binary, expected

    for jobs in ("1", "2"):
        run("build", "--jobs", jobs)
        expect()
    run("format")
    formatted = (root / "src/main.enq").read_text()
    assert "__version__" in formatted and "__project_name__" in formatted and "1.2.3" not in formatted
    for args in (("check",), ("check", "src/main.enq"), ("lint",), ("format", "--check"),
                 ("test", "--jobs", "2")):
        run(*args)
    assert (root / "src/main.enq").read_text() == formatted
    manifest(dependency, "metadata_dependency", "2.2.0")
    run("build", "--jobs", "2")
    expect(lib="2.2.0")
    manifest(root, "renamed_app", "1.2.4")
    run("build", "--jobs", "1")
    expect(app="1.2.4", lib="2.2.0", name="renamed_app")
    manifest(root, "renamed_app", "1.2.5")
    run("build", "--jobs", "2")
    expect(app="1.2.5", lib="2.2.0", name="renamed_app")
    manifest(root, "renamed_app", None)
    run("build", "--jobs", "2")
    binary, expected = expect(app="0.0.0", lib="2.2.0", name="renamed_app")
    (root / "encore.toml").unlink()
    (dependency / "encore.toml").unlink()
    result = subprocess.run([str(binary)], cwd=temporary, env=env, capture_output=True, timeout=15)
    assert result.returncode == 0 and result.stdout.replace(b"\r\n", b"\n") == expected
    manifest(dependency, "metadata_dependency", "2.2.0")
    manifest(root, "renamed_app", "1.2.4")
    negative = [
        'fn main() { let __version__ = "fake" }',
        'fn value(__project_name__: str) -> str { ret __project_name__ }\nfn main() {}',
        'fn main() { let callback = |__version__: str| __version__ }',
        'static __version__: str = \"fake\"\nfn main() {}',
        'fn __version__() {}',
        'import metadata_dependency::identity as __project_name__\nfn main() {}',
        'fn main() { __version__ = "fake" }',
    ]
    failures = []
    for text in negative:
        write(root / "src/main.enq", text + '\n')
        result = subprocess.run([compiler, "check"], cwd=root, env=env, capture_output=True, timeout=240)
        if result.returncode == 0 or b"compiler constant" not in result.stdout + result.stderr:
            failures.append((text, result.returncode, result.stdout, result.stderr))
    assert not failures, failures
    write(root / "src/main.enq", 'fn main() -> u32 { let __other__ = 7_u32 ret __other__ - 7_u32 }\n')
    run("build")
    # A package containing only ordinary functions has no generic-body digest
    # to incidentally invalidate lowering after a metadata-only change.
    write(dependency / "src/lib.enq", 'pub fn identity() -> str { ret __version__ }\n')
    write(root / "src/main.enq", 'import std::io::println\nimport metadata_dependency::identity\nfn main() -> u32 { println(identity()) ret 0_u32 }\n')
    run("build", "--jobs", "2")
    simple_binary = root / "target/dev" / ("renamed_app.exe" if os.name == "nt" else "renamed_app")
    for version in ("2.3.0", '2.4.0-β"\\\n\t'):
        manifest(dependency, "metadata_dependency", version)
        run("build", "--jobs", "2")
        result = subprocess.run([str(simple_binary)], capture_output=True, timeout=15)
        assert result.returncode == 0 and result.stdout.replace(b"\r\n", b"\n") == (version + "\n").encode(), result
    print("project/library ownership, generics, macros, f-strings, cache updates, defaults, tooling and bindings: passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=lambda x: str(Path(x).resolve()))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="encore-project-constants-") as directory:
        root = Path(directory)
        compiler_tests(args.compiler, root)


if __name__ == "__main__":
    main()

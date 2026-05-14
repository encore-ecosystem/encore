import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ehir.compiler import EHIR_ProjectCompiler, Refrain
from ehir.frontend.builtin import EHIR_DirectFrontend

from ehir_llvm_backend import EHIR_LLVM_Backend

AVAILABLE_TARGETS = {
    "debug": EHIR_LLVM_Backend.OptProfile.debug,
    "release": EHIR_LLVM_Backend.OptProfile.release,
    "extreme": EHIR_LLVM_Backend.OptProfile.extreme,
}

AVAILABLE_ROOT_TYPES = {
    "executable": Refrain.TargetType.EXECUTABLE,
    "static_lib": Refrain.TargetType.STATIC_LIB,
    "object": Refrain.TargetType.OBJECT,
}


@dataclass(frozen=True)
class _TestCase:
    source_file: Path
    entrypoint: str

    @property
    def display_name(self) -> str:
        return self.source_file.as_posix()


def _add_dependency_refrains(compiler: EHIR_ProjectCompiler, cwd: Path):
    refrains_dir = cwd / "refrains"
    if not refrains_dir.exists():
        return
    for refrain in refrains_dir.iterdir():
        if not refrain.is_dir():
            continue
        compiler.add_refrain_to_build(Refrain(name=refrain.name, path=refrain, type=Refrain.TargetType.STATIC_LIB))


def _create_compiler(cwd: Path, target: str, target_dir: Path | None = None) -> EHIR_ProjectCompiler:
    out_dir = target_dir if target_dir is not None else cwd / "target"
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(),
        backend=EHIR_LLVM_Backend(target_dir=out_dir, opt_profile=AVAILABLE_TARGETS[target]),
    )
    _add_dependency_refrains(compiler, cwd)
    return compiler


def _build_project(cwd: Path, *, target: str, target_dir: Path | None, root_type: str):
    compiler = _create_compiler(cwd, target=target, target_dir=target_dir)
    compiler.add_refrain_to_build(Refrain(name=cwd.name, path=cwd, type=AVAILABLE_ROOT_TYPES[root_type]))
    compiler.compile_all()


def _collect_tests(cwd: Path) -> list[_TestCase]:
    tests_dir = cwd / "tests"
    if not tests_dir.exists():
        return []

    cases: list[_TestCase] = []
    for source_file in sorted(tests_dir.rglob("*.ehir")):
        rel = source_file.relative_to(tests_dir)
        entrypoint = rel.with_suffix("").as_posix()
        cases.append(_TestCase(source_file=source_file, entrypoint=entrypoint))
    return cases


def _run_tests(cwd: Path, *, target: str, target_dir: Path | None) -> int:
    tests = _collect_tests(cwd)
    if not tests:
        print("No tests found.")
        return 0

    passed = 0
    failed = 0
    for idx, test in enumerate(tests, start=1):
        compiler = _create_compiler(cwd, target=target, target_dir=target_dir)
        test_name = f"{cwd.name}__test__{test.entrypoint.replace('/', '__')}"
        compiler.add_refrain_to_build(
            Refrain(
                name=test_name,
                path=cwd,
                type=Refrain.TargetType.EXECUTABLE,
                entry_root="tests",
                entrypoint=test.entrypoint,
            )
        )

        try:
            outputs = dict(compiler.compile_all())
            binary_path = outputs[test_name]
            result = subprocess.run([str(binary_path)], check=False)
            if result.returncode == 0:
                passed += 1
                print(f"[{idx}/{len(tests)}] ok {test.display_name}")
            else:
                failed += 1
                print(f"[{idx}/{len(tests)}] FAILED {test.display_name} (exit code {result.returncode})")
        except Exception as exc:
            failed += 1
            print(f"[{idx}/{len(tests)}] FAILED {test.display_name} ({exc})")

    if failed == 0:
        print(f"PASS {passed} tests")
        return 0
    print(f"FAIL {failed} failed, {passed} passed")
    return 1


def main():
    parser = argparse.ArgumentParser(prog="ehir-llvm-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build current EHIR project")
    build_parser.add_argument(
        "--target",
        default="debug",
        choices=AVAILABLE_TARGETS.keys(),
        help="Build target profile",
    )
    build_parser.add_argument("--target-dir", default=None, help="Output directory (defaults to <cwd>/target)")
    build_parser.add_argument(
        "--root-type",
        default="executable",
        choices=AVAILABLE_ROOT_TYPES.keys(),
        help="Artifact type for root refrain",
    )

    test_parser = subparsers.add_parser("test", help="Run tests from ./tests (*.ehir with fn main)")
    test_parser.add_argument(
        "--target",
        default="debug",
        choices=AVAILABLE_TARGETS.keys(),
        help="Build target profile",
    )
    test_parser.add_argument("--target-dir", default=None, help="Output directory (defaults to <cwd>/target)")

    args = parser.parse_args()

    cwd = Path().resolve()
    target_dir = Path(args.target_dir).resolve() if args.target_dir is not None else None

    if args.command == "build":
        _build_project(cwd, target=args.target, target_dir=target_dir, root_type=args.root_type)
        return
    if args.command == "test":
        raise SystemExit(_run_tests(cwd, target=args.target, target_dir=target_dir))


if __name__ == "__main__":
    main()

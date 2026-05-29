import argparse
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ehir.cfg import default_cfg_environment
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
class _CfreeExpectations:
    free_ids: tuple[str, ...] | None = None

    @property
    def enabled(self) -> bool:
        return self.free_ids is not None


@dataclass(frozen=True)
class _TestCase:
    source_file: Path
    entrypoint: str
    cfree_expectations: _CfreeExpectations
    expected_compile_error: str | None = None

    @property
    def display_name(self) -> str:
        return self.source_file.as_posix()


_CFREE_FREE_IDS_RE = re.compile(r"^\[cfree\] free heap payload of .+ id=(?P<id>.+)$")


def _parse_cfree_expectations(source_file: Path) -> _CfreeExpectations:
    free_ids: tuple[str, ...] | None = None
    for raw_line in source_file.read_text().splitlines():
        line = raw_line.strip()
        if not line.startswith(";@"):
            continue
        if line.startswith(";@cfree.free_ids="):
            value = line.split("=", 1)[1].strip()
            if value:
                free_ids = tuple(part.strip() for part in value.split(",") if part.strip())
            else:
                free_ids = tuple()
    return _CfreeExpectations(free_ids=free_ids)


def _parse_expected_compile_error(source_file: Path) -> str | None:
    expected: str | None = None
    for raw_line in source_file.read_text().splitlines():
        line = raw_line.strip()
        if not line.startswith(";@"):
            continue
        if line.startswith(";@expect.compile_error="):
            expected = line.split("=", 1)[1].strip() or ""
    return expected


def _extract_cfree_free_ids(output: str) -> list[str]:
    ids: list[str] = []
    for line in output.splitlines():
        match = _CFREE_FREE_IDS_RE.match(line.strip())
        if match is not None:
            ids.append(match.group("id"))
    return ids


def _validate_cfree_expectations(test: _TestCase, output: str) -> str | None:
    exp = test.cfree_expectations
    if exp.free_ids is None:
        return None
    actual_ids = _extract_cfree_free_ids(output)
    expected_counter = Counter(exp.free_ids)
    actual_counter = Counter(actual_ids)
    if expected_counter != actual_counter:
        expected = ", ".join(sorted(exp.free_ids))
        actual = ", ".join(sorted(actual_ids))
        return (
            "cfree free-id set mismatch: "
            f"expected {{{expected}}}, got {{{actual}}}"
        )
    return None


def _exception_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        text = str(current).strip()
        if text:
            parts.append(text)
        current = current.__cause__ or current.__context__
    return " | caused by: ".join(parts)


def _add_dependency_refrains(compiler: EHIR_ProjectCompiler, cwd: Path):
    refrains_dir = cwd / "refrains"
    if not refrains_dir.exists():
        return
    for refrain in refrains_dir.iterdir():
        if not refrain.is_dir():
            continue
        compiler.add_refrain_to_build(Refrain(name=refrain.name, path=refrain, type=Refrain.TargetType.STATIC_LIB))


def _create_compiler(
    cwd: Path,
    target: str,
    target_dir: Path | None = None,
    trace_cfree: bool = False,
    cfg_overrides: list[str] | None = None,
) -> EHIR_ProjectCompiler:
    out_dir = target_dir if target_dir is not None else cwd / "target"
    cfg_environment = default_cfg_environment(backend="llvm", extra=cfg_overrides or [])
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_DirectFrontend(cfg_environment=cfg_environment),
        backend=EHIR_LLVM_Backend(target_dir=out_dir, opt_profile=AVAILABLE_TARGETS[target]),
        trace_cfree=trace_cfree,
        cfg_environment=cfg_environment,
    )
    _add_dependency_refrains(compiler, cwd)
    return compiler


def _build_project(
    cwd: Path,
    *,
    target: str,
    target_dir: Path | None,
    root_type: str,
    trace_cfree: bool,
    cfg_overrides: list[str] | None,
):
    compiler = _create_compiler(
        cwd,
        target=target,
        target_dir=target_dir,
        trace_cfree=trace_cfree,
        cfg_overrides=cfg_overrides,
    )
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
        cases.append(
            _TestCase(
                source_file=source_file,
                entrypoint=entrypoint,
                cfree_expectations=_parse_cfree_expectations(source_file),
                expected_compile_error=_parse_expected_compile_error(source_file),
            )
        )
    return cases


def _run_tests(
    cwd: Path,
    *,
    target: str,
    target_dir: Path | None,
    trace_cfree: bool,
    cfg_overrides: list[str] | None,
) -> int:
    tests = _collect_tests(cwd)
    if not tests:
        print("No tests found.")
        return 0

    passed = 0
    failed = 0
    for idx, test in enumerate(tests, start=1):
        needs_trace = trace_cfree or test.cfree_expectations.enabled
        compiler = _create_compiler(
            cwd,
            target=target,
            target_dir=target_dir,
            trace_cfree=needs_trace,
            cfg_overrides=cfg_overrides,
        )
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
            if test.expected_compile_error is not None:
                failed += 1
                print(
                    f"[{idx}/{len(tests)}] FAILED {test.display_name} "
                    f"(expected compile error containing '{test.expected_compile_error}')"
                )
                continue
            binary_path = outputs[test_name]
            result = subprocess.run([str(binary_path)], check=False, text=True, capture_output=True)
            output = result.stdout + result.stderr
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")
            if result.returncode == 0:
                expectation_error = _validate_cfree_expectations(test, output)
                if expectation_error is None:
                    passed += 1
                    print(f"[{idx}/{len(tests)}] ok {test.display_name}")
                else:
                    failed += 1
                    print(f"[{idx}/{len(tests)}] FAILED {test.display_name} ({expectation_error})")
            else:
                failed += 1
                print(f"[{idx}/{len(tests)}] FAILED {test.display_name} (exit code {result.returncode})")
        except Exception as exc:
            error_text = _exception_text(exc)
            if test.expected_compile_error is not None and test.expected_compile_error in error_text:
                passed += 1
                print(f"[{idx}/{len(tests)}] ok {test.display_name} (expected compile error)")
            else:
                failed += 1
                print(f"[{idx}/{len(tests)}] FAILED {test.display_name} ({error_text})")

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
    build_parser.add_argument(
        "--trace-cfree",
        action="store_true",
        help="Print debug messages right before cfree deallocations.",
    )
    build_parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )

    test_parser = subparsers.add_parser("test", help="Run tests from ./tests (*.ehir with fn main)")
    test_parser.add_argument(
        "--target",
        default="debug",
        choices=AVAILABLE_TARGETS.keys(),
        help="Build target profile",
    )
    test_parser.add_argument("--target-dir", default=None, help="Output directory (defaults to <cwd>/target)")
    test_parser.add_argument(
        "--trace-cfree",
        action="store_true",
        help="Print debug messages right before cfree deallocations.",
    )
    test_parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )

    args = parser.parse_args()

    cwd = Path().resolve()
    target_dir = Path(args.target_dir).resolve() if args.target_dir is not None else None

    if args.command == "build":
        _build_project(
            cwd,
            target=args.target,
            target_dir=target_dir,
            root_type=args.root_type,
            trace_cfree=args.trace_cfree,
            cfg_overrides=args.cfg,
        )
        return
    if args.command == "test":
        raise SystemExit(
            _run_tests(
                cwd,
                target=args.target,
                target_dir=target_dir,
                trace_cfree=args.trace_cfree,
                cfg_overrides=args.cfg,
            )
        )


if __name__ == "__main__":
    main()

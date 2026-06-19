import subprocess
import sys
from argparse import Namespace, SUPPRESS
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console

from ehir import Refrain
from encore import ENCORE_CACHE_DIR
from encore.modes.build import (
    AVAILABLE_BACKENDS,
    AVAILABLE_OPTPROFILES,
    _BuildScriptContext,
    _inject_mandatory_core_dependency,
    _load_refrain,
    _resolve_dependency,
    create_compiler,
    load_manifest,
    print_profile_report,
    profile_timings_enabled,
    resolve_build_profile,
    run_binary,
)
from encore.utils.manifest import ProjectManifest


@dataclass(frozen=True)
class _TestCase:
    refrain_name: str
    refrain_path: Path
    source_file: Path
    entry_root: str
    entrypoint: str
    expected_compile_error: str | None = None

    @property
    def display_name(self) -> str:
        rel = self.source_file.relative_to(self.refrain_path)
        return f"{self.refrain_name}:{rel.as_posix()}"


def add_test_parser(subparsers) -> tuple[str, Callable]:
    section = "test"
    test_parser = subparsers.add_parser(section, help="Run unit tests in tests/ of all loaded refrains")
    test_parser.add_argument(
        "--backend", default="llvm", choices=set(AVAILABLE_BACKENDS), help="EHIR Compiler Backend"
    )
    test_parser.add_argument(
        "--opt-profile",
        default=None,
        choices=set(AVAILABLE_OPTPROFILES.keys()),
        help="Optimization profile. Defaults to debug.",
    )
    test_parser.add_argument(
        "--profile",
        nargs="?",
        const="timings",
        default=None,
        choices={*AVAILABLE_OPTPROFILES.keys(), "timings"},
        help=(
            "Enable compiler timing profile when passed without a value. "
            "For compatibility, --profile debug|release|extreme still selects the optimization profile."
        ),
    )
    test_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    test_parser.add_argument("--filter", type=str, default=None, help="Only run tests whose path contains this text")
    test_parser.add_argument("-j", "--jobs", type=int, default=1, help="Number of test worker processes to run")
    test_parser.add_argument("--_worker-source", dest="_worker_source", type=str, default=None, help=SUPPRESS)
    test_parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )
    return (section, handle_test)


def handle_test(args: Namespace):
    cwd = Path().resolve()
    console = Console(highlight=False)
    args.resolved_profile = resolve_build_profile(args)
    args.profile_timings = profile_timings_enabled(args)
    if args._worker_source is not None:
        _handle_test_worker(args, cwd)
        return

    tests = _collect_test_cases(cwd, args.filter)
    if not tests:
        console.print("No tests found.")
        return

    if args.profile_timings:
        _run_tests_in_process(args, cwd, console, tests)
        return

    jobs = _normalize_jobs(args.jobs)
    passed = 0
    failed = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(_run_test_worker, args, cwd, test): test for test in tests}
        for future in as_completed(futures):
            test = futures[future]
            completed += 1
            try:
                result = future.result()
            except Exception as exc:
                failed += 1
                console.print(f"[{completed}/{len(tests)}] [red]FAILED[/red] {test.display_name} ({_exception_text(exc)})")
                continue

            if result.returncode == 0:
                passed += 1
                suffix = " (expected compile error)" if test.expected_compile_error is not None else ""
                console.print(f"[{completed}/{len(tests)}] [green]ok[/green] {test.display_name}{suffix}")
            else:
                failed += 1
                console.print(
                    f"[{completed}/{len(tests)}] [red]FAILED[/red] {test.display_name} ({_format_worker_error(result)})"
                )

    if failed == 0:
        console.print(f"[green]PASS[/green] {passed} tests")
        return

    console.print(f"[red]FAIL[/red] {failed} failed, {passed} passed")
    raise SystemExit(1)


def _run_tests_in_process(args: Namespace, cwd: Path, console: Console, tests: list[_TestCase]) -> None:
    passed = 0
    failed = 0
    for completed, test in enumerate(tests, start=1):
        try:
            _run_test_case(args, cwd, test)
        except Exception as exc:
            failed += 1
            console.print(f"[{completed}/{len(tests)}] [red]FAILED[/red] {test.display_name} ({_exception_text(exc)})")
            continue
        passed += 1
        suffix = " (expected compile error)" if test.expected_compile_error is not None else ""
        console.print(f"[{completed}/{len(tests)}] [green]ok[/green] {test.display_name}{suffix}")

    if failed == 0:
        console.print(f"[green]PASS[/green] {passed} tests")
        return

    console.print(f"[red]FAIL[/red] {failed} failed, {passed} passed")
    raise SystemExit(1)


def _normalize_jobs(jobs: int) -> int:
    if jobs < 1:
        raise RuntimeError("--jobs must be greater than zero")
    return jobs


def _handle_test_worker(args: Namespace, cwd: Path) -> None:
    source_file = Path(args._worker_source).resolve()
    tests = _collect_test_cases(cwd, None)
    for test in tests:
        if test.source_file.resolve() == source_file:
            _run_test_case(args, cwd, test)
            return
    raise RuntimeError(f"Unknown test source: {source_file}")


def _run_test_worker(args: Namespace, cwd: Path, test: _TestCase) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-c",
        "from encore.cli import main; main()",
        "test",
        "--backend",
        args.backend,
        "--profile",
        args.resolved_profile,
        "--_worker-source",
        str(test.source_file),
    ]
    if args.no_cache:
        cmd.append("--no-cache")
    for cfg in args.cfg:
        cmd.extend(["--cfg", cfg])

    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _run_test_case(args: Namespace, cwd: Path, test: _TestCase) -> None:
    test_name = _build_test_refrain_name(test)
    compiler = create_compiler(
        cwd,
        args.backend,
        args.resolved_profile,
        no_cache=args.no_cache,
        cfg_overrides=args.cfg,
        target_dir=_test_worker_target_dir(cwd, test_name),
        cache_dir=_test_shared_cache_dir(cwd, args.resolved_profile),
        profile_timings=args.profile_timings,
    )
    compiler.on_refrain = lambda _refrain: None
    build_ctx = _BuildScriptContext(
        backend=args.backend,
        profile=args.resolved_profile,
        no_cache=args.no_cache,
        cfg_overrides=tuple(args.cfg),
        workspace_suffix=test_name,
    )
    _inject_mandatory_core_dependency(compiler, test.refrain_path, build_ctx)
    ref = _load_refrain(
        compiler,
        test.refrain_path,
        type=Refrain.TargetType.EXECUTABLE,
        build_ctx=build_ctx,
        name=test_name,
        entry_root=test.entry_root,
        entrypoint=test.entrypoint,
    )

    if test.expected_compile_error is not None:
        _assert_expected_compile_error(compiler, ref, test.expected_compile_error)
        if args.profile_timings:
            print_profile_report(compiler)
        return

    outputs = compiler.compile_all()
    if args.profile_timings:
        print_profile_report(compiler)
    output_by_name = dict(outputs)
    binary_path = output_by_name[test_name]
    ret_code = run_binary(binary_path, [])
    if ret_code != 0:
        raise RuntimeError(f"exit code {ret_code}")


def _assert_expected_compile_error(compiler, ref: Refrain, expected: str) -> None:
    try:
        compiler.prepare_refrain(ref)
    except Exception as exc:
        error_text = _exception_text(exc)
        if expected in error_text:
            return
        raise
    raise RuntimeError(f"expected compile error containing '{expected}'")


def _test_worker_target_dir(cwd: Path, test_name: str) -> Path:
    return cwd / "target" / "tests" / test_name


def _test_shared_cache_dir(cwd: Path, profile: str) -> Path:
    return cwd / "target" / profile / "ehir" / "cache"


def _format_worker_error(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if output:
        return output
    if result.returncode < 0:
        return f"worker terminated by signal {-result.returncode}"
    return f"worker exited with code {result.returncode}"


def _collect_test_cases(root: Path, filter_text: str | None) -> list[_TestCase]:
    refrains = _collect_refrain_roots(root)
    tests: list[_TestCase] = []

    for refrain_name in sorted(refrains):
        refrain_path = refrains[refrain_name]
        tests_dir = refrain_path / "tests"
        if not tests_dir.exists():
            continue
        for source_file in sorted(tests_dir.rglob("*.enq")):
            rel_to_tests = source_file.relative_to(tests_dir)
            entrypoint = rel_to_tests.with_suffix("").as_posix()
            test = _TestCase(
                refrain_name=refrain_name,
                refrain_path=refrain_path,
                source_file=source_file,
                entry_root="tests",
                entrypoint=entrypoint,
                expected_compile_error=_parse_expected_compile_error(source_file),
            )
            if filter_text and filter_text not in test.display_name:
                continue
            tests.append(test)

    return tests


def _collect_refrain_roots(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}

    def visit(path: Path):
        manifest = load_manifest(path)
        if manifest.project.name in result:
            return
        result[manifest.project.name] = path

        for dep in manifest.project.dependencies:
            visit(_resolve_dependency(dep, path))

    visit(root)

    if "core" not in result:
        core_path = _resolve_local_core_root(root)
        if core_path is not None:
            visit(core_path)

    return result


def _resolve_local_core_root(project_root: Path) -> Optional[Path]:
    candidates: list[Path] = []
    for base in [project_root, *project_root.parents]:
        candidates.append(base / "refrains" / "core")
        candidates.append(base / "core")
    candidates.append(Path(__file__).resolve().parents[3] / "enc_future" / "refrains" / "core")
    candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "core")
    candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "encore-core")

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        manifest_path = candidate / ProjectManifest.default_filename()
        if not manifest_path.exists():
            continue
        manifest = load_manifest(candidate)
        if manifest.project.name == "core":
            return candidate
    return None


def _parse_expected_compile_error(source_file: Path) -> str | None:
    expected: str | None = None
    for raw_line in source_file.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith("//@expect.compile_error="):
            expected = line.split("=", 1)[1].strip() or ""
        if line.startswith("// @expect.compile_error="):
            expected = line.split("=", 1)[1].strip() or ""
    return expected


def _exception_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        parts.append(text if text else current.__class__.__name__)
        current = current.__cause__ or current.__context__
    return " | caused by: ".join(parts)


def _build_test_refrain_name(test: _TestCase) -> str:
    stem = test.source_file.relative_to(test.refrain_path).with_suffix("").as_posix()
    normalized = []
    for ch in stem:
        if ch.isalnum():
            normalized.append(ch)
        else:
            normalized.append("_")
    return f"{test.refrain_name}__test__{''.join(normalized)}"

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console

from ehir import CompiledRefrain, Refrain
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
        "--profile", default="debug", choices=set(AVAILABLE_OPTPROFILES.keys()), help="Optimization profile"
    )
    test_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    test_parser.add_argument("--filter", type=str, default=None, help="Only run tests whose path contains this text")
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

    tests = _collect_test_cases(cwd, args.filter)
    if not tests:
        console.print("No tests found.")
        return

    passed = 0
    failed = 0
    shared_compiled_refrains: dict[str, CompiledRefrain] = {}
    for idx, test in enumerate(tests, start=1):
        test_name = _build_test_refrain_name(test)
        compiler = create_compiler(cwd, args.backend, args.profile, no_cache=args.no_cache, cfg_overrides=args.cfg)
        compiler.compiled_refrains.update(shared_compiled_refrains)
        compiler.on_refrain = lambda _refrain: None
        build_ctx = _BuildScriptContext(
            backend=args.backend,
            profile=args.profile,
            no_cache=args.no_cache,
            cfg_overrides=tuple(args.cfg),
        )
        _inject_mandatory_core_dependency(compiler, test.refrain_path, build_ctx)
        _load_refrain(
            compiler,
            test.refrain_path,
            type=Refrain.TargetType.EXECUTABLE,
            build_ctx=build_ctx,
            name=test_name,
            entry_root=test.entry_root,
            entrypoint=test.entrypoint,
        )

        try:
            outputs = compiler.compile_all()
            _share_compiled_dependencies(shared_compiled_refrains, compiler.compiled_refrains, test_name)
            if test.expected_compile_error is not None:
                failed += 1
                console.print(
                    f"[{idx}/{len(tests)}] [red]FAILED[/red] {test.display_name} "
                    f"(expected compile error containing '{test.expected_compile_error}')"
                )
                continue
            output_by_name = dict(outputs)
            binary_path = output_by_name[test_name]
            ret_code = run_binary(binary_path, [])
            if ret_code == 0:
                passed += 1
                console.print(f"[{idx}/{len(tests)}] [green]ok[/green] {test.display_name}")
            else:
                failed += 1
                console.print(f"[{idx}/{len(tests)}] [red]FAILED[/red] {test.display_name} (exit code {ret_code})")
        except Exception as exc:
            error_text = _exception_text(exc)
            if test.expected_compile_error is not None and test.expected_compile_error in error_text:
                passed += 1
                console.print(f"[{idx}/{len(tests)}] [green]ok[/green] {test.display_name} (expected compile error)")
            else:
                failed += 1
                console.print(f"[{idx}/{len(tests)}] [red]FAILED[/red] {test.display_name} ({error_text})")

    if failed == 0:
        console.print(f"[green]PASS[/green] {passed} tests")
        return

    console.print(f"[red]FAIL[/red] {failed} failed, {passed} passed")
    raise SystemExit(1)


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
    while current is not None:
        text = str(current).strip()
        parts.append(text if text else current.__class__.__name__)
        current = current.__cause__ or current.__context__
    return " | caused by: ".join(parts)


def _share_compiled_dependencies(
    shared: dict[str, CompiledRefrain],
    compiled: dict[str, CompiledRefrain],
    test_name: str,
) -> None:
    for name, compiled_refrain in compiled.items():
        if name == test_name:
            continue
        if compiled_refrain.type != Refrain.TargetType.OBJECT:
            continue
        shared[name] = compiled_refrain


def _build_test_refrain_name(test: _TestCase) -> str:
    stem = test.source_file.relative_to(test.refrain_path).with_suffix("").as_posix()
    normalized = []
    for ch in stem:
        if ch.isalnum():
            normalized.append(ch)
        else:
            normalized.append("_")
    return f"{test.refrain_name}__test__{''.join(normalized)}"

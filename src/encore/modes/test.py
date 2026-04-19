from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console

from ehir import Refrain
from encore import ENCORE_CACHE_DIR
from encore.modes.build import (
    AVAILABLE_BACKENDS,
    AVAILABLE_OPTPROFILES,
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
    entrypoint: str

    @property
    def display_name(self) -> str:
        rel = self.source_file.relative_to(self.refrain_path)
        return f"{self.refrain_name}:{rel.as_posix()}"


def add_test_parser(subparsers) -> tuple[str, Callable]:
    section = "test"
    test_parser = subparsers.add_parser(section, help="Run unit tests in src/tests of all loaded refrains")
    test_parser.add_argument(
        "--backend", default="llvm", choices=set(AVAILABLE_BACKENDS.keys()), help="EHIR Compiler Backend"
    )
    test_parser.add_argument(
        "--profile", default="debug", choices=set(AVAILABLE_OPTPROFILES.keys()), help="Optimization profile"
    )
    test_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    test_parser.add_argument("--filter", type=str, default=None, help="Only run tests whose path contains this text")
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
    for idx, test in enumerate(tests, start=1):
        test_name = _build_test_refrain_name(test)
        compiler = create_compiler(cwd, args.backend, args.profile, no_cache=args.no_cache)
        compiler.on_refrain = lambda _refrain: None
        compiler.add_refrain_to_build(
            Refrain(
                name=test_name,
                path=test.refrain_path,
                type=Refrain.TargetType.EXECUTABLE,
                entrypoint=test.entrypoint,
            )
        )

        try:
            outputs = compiler.compile_all()
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
            failed += 1
            console.print(f"[{idx}/{len(tests)}] [red]FAILED[/red] {test.display_name} ({exc})")

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
            rel_to_src = source_file.relative_to(refrain_path / "src")
            entrypoint = rel_to_src.with_suffix("").as_posix()
            test = _TestCase(
                refrain_name=refrain_name,
                refrain_path=refrain_path,
                source_file=source_file,
                entrypoint=entrypoint,
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


def _build_test_refrain_name(test: _TestCase) -> str:
    stem = test.source_file.relative_to(test.refrain_path / "src").with_suffix("").as_posix()
    normalized = []
    for ch in stem:
        if ch.isalnum():
            normalized.append(ch)
        else:
            normalized.append("_")
    return f"{test.refrain_name}__test__{''.join(normalized)}"

from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

from encore.frontend import EHIR_EncoreFrontend, format_module_reflection, format_symbol_reflection


def add_inspect_parser(subparsers) -> tuple[str, Callable]:
    section = "inspect"
    inspect_parser = subparsers.add_parser(section, help="Inspect typed frontend reflection for a module or symbol")
    inspect_parser.add_argument(
        "--module",
        default=None,
        help="Module path (.enq file, module::path, src-relative path, or tests-relative path). Defaults to src/main.enq or src/lib.enq.",
    )
    inspect_parser.add_argument("--symbol", default=None, help="Optional symbol query inside the module")
    return (section, handle_inspect)


def handle_inspect(args: Namespace):
    cwd = Path().resolve()
    module_id = _resolve_inspect_module(cwd, args.module)
    frontend = EHIR_EncoreFrontend(src_dir=cwd / "src")

    if args.symbol is not None:
        symbol = frontend.get_symbol_reflection_by_id(module_id, args.symbol)
        if symbol is None:
            raise RuntimeError(f"Unable to find symbol '{args.symbol}' in module '{module_id}'")
        print(format_symbol_reflection(symbol))
        return

    print(format_module_reflection(frontend.get_reflection_by_id(module_id)))


def _resolve_inspect_module(project_root: Path, module_arg: str | None) -> Path:
    if module_arg is None:
        for candidate in (project_root / "src" / "main.enq", project_root / "src" / "lib.enq"):
            if candidate.exists():
                return candidate.resolve()
        raise RuntimeError("Unable to resolve default inspect module: expected src/main.enq or src/lib.enq")

    explicit = (project_root / module_arg).resolve()
    if explicit.exists():
        return explicit

    if module_arg.endswith(".enq"):
        explicit_path = Path(module_arg).expanduser().resolve()
        if explicit_path.exists():
            return explicit_path

    normalized = module_arg.replace("::", "/").strip("/")
    if normalized.startswith("src/"):
        candidates = [project_root / normalized]
    elif normalized.startswith("tests/"):
        candidates = [project_root / normalized]
    else:
        candidates = [
            project_root / "src" / normalized,
            project_root / "tests" / normalized,
        ]

    resolved = _resolve_module_candidates(candidates)
    if resolved is not None:
        return resolved

    raise RuntimeError(f"Unable to resolve inspect module '{module_arg}'")


def _resolve_module_candidates(candidates: list[Path]) -> Path | None:
    for base in candidates:
        if base.suffix == ".enq" and base.exists():
            return base.resolve()

        file_candidate = base.with_suffix(".enq")
        if file_candidate.exists():
            return file_candidate.resolve()

        mod_candidate = base / "mod.enq"
        if mod_candidate.exists():
            return mod_candidate.resolve()

    return None

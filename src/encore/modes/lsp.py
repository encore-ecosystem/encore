import os
import shutil
from argparse import Namespace
from pathlib import Path
from typing import Callable

from encore import PROJECT_ROOT


def add_lsp_parser(subparsers) -> tuple[str, Callable]:
    section = "lsp"
    lsp_parser = subparsers.add_parser(section, help="Run the Encore language server")
    lsp_parser.add_argument(
        "--server",
        type=str,
        default=None,
        help="Path to an encore-lsp executable. Defaults to PATH or the repository lsp build.",
    )
    return (section, handle_lsp)


def handle_lsp(args: Namespace) -> None:
    server = _resolve_lsp_server(args.server)
    if server is None:
        raise RuntimeError(
            "Unable to find encore-lsp. Build it from the repository lsp project or install it with "
            "`encore install --path <encore>/lsp`."
        )

    os.execv(str(server), [str(server)])


def _resolve_lsp_server(explicit_path: str | None) -> Path | None:
    if explicit_path is not None:
        return _existing_executable(Path(explicit_path).expanduser())

    for name in _server_names():
        path = shutil.which(name)
        if path is not None:
            return Path(path)

    for path in _repository_candidates():
        executable = _existing_executable(path)
        if executable is not None:
            return executable

    return None


def _server_names() -> tuple[str, ...]:
    suffix = ".exe" if os.name == "nt" else ""
    return (f"encore-lsp{suffix}", f"encore_lsp{suffix}")


def _repository_candidates() -> list[Path]:
    candidates: list[Path] = []
    for profile in ("release", "debug"):
        for name in _server_names():
            candidates.append(PROJECT_ROOT / "lsp" / "target" / profile / name)
    return candidates


def _existing_executable(path: Path) -> Path | None:
    resolved = path.resolve()
    if resolved.is_file() and os.access(resolved, os.X_OK):
        return resolved
    return None

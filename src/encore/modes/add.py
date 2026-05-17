from argparse import Namespace
from pathlib import Path
from typing import Callable

from rich.console import Console

from encore.modes.build import _resolve_dependency, load_manifest, save_manifest, sync_dependencies, write_lockfile

INDEX_GITHUB_PREFIX = "git@https://github.com/encore-language-index/"
SYSTEM_REF_PREFIX = "sys@"


def add_add_parser(subparsers) -> tuple[str, Callable]:
    section = "add"
    add_parser = subparsers.add_parser(section, help="Add refrain")
    add_parser.add_argument(
        "dependency",
        type=str,
        help="Dependency reference: <name> | git@<repo> | path@<path>",
    )
    return (section, handle_add)


def handle_add(args: Namespace):
    cwd = Path().resolve()
    manifest = load_manifest(cwd)
    console = Console(highlight=False)

    dep_ref = _normalize_dependency_ref(args.dependency)

    if dep_ref in manifest.project.dependencies:
        console.print(f"Dependency already exists: {dep_ref}")
        return

    _resolve_dependency(dep_ref, cwd)
    manifest.project.dependencies.append(dep_ref)
    save_manifest(cwd, manifest)
    resolved = sync_dependencies(cwd, update=False)
    write_lockfile(cwd, resolved)
    console.print(f"Added: {dep_ref}")


def _normalize_dependency_ref(raw: str) -> str:
    if raw.startswith(SYSTEM_REF_PREFIX):
        raise RuntimeError("System dependencies are managed by Encore and cannot be added manually")
    if raw.startswith("git@") or raw.startswith("path@"):
        return raw
    return f"{INDEX_GITHUB_PREFIX}{raw}"

from argparse import Namespace
from pathlib import Path
from typing import Callable

from encore.modes.build import _resolve_dependency, load_manifest, save_manifest


def add_add_parser(subparsers) -> tuple[str, Callable]:
    section = "add"
    add_parser = subparsers.add_parser(section, help="Add refrain")
    add_parser.add_argument("dependency", type=str, help="Dependency reference, e.g. git@... or path@...")
    return (section, handle_add)


def handle_add(args: Namespace):
    cwd = Path().resolve()
    manifest = load_manifest(cwd)

    if args.dependency in manifest.project.dependencies:
        return

    _resolve_dependency(args.dependency)
    manifest.project.dependencies.append(args.dependency)
    save_manifest(cwd, manifest)

from argparse import Namespace
from pathlib import Path
from typing import Callable

from rich.console import Console

from encore.modes.build import sync_dependencies, write_lockfile


def add_update_parser(subparsers) -> tuple[str, Callable]:
    section = "update"
    _update_parser = subparsers.add_parser(section, help="Update all refrains")
    return (section, handle_update)


def handle_update(args: Namespace):
    cwd = Path().resolve()
    console = Console(highlight=False)
    resolved = sync_dependencies(cwd, update=True, ignore_errors=False)
    write_lockfile(cwd, resolved)
    console.print(f"Updated {len(resolved)} packages -> encore.lock")

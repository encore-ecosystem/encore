from argparse import Namespace
from pathlib import Path
from typing import Callable

from rich.console import Console

from encore.modes.build import sync_dependencies, write_lockfile


def add_sync_parser(subparsers) -> tuple[str, Callable]:
    section = "sync"
    sync_parser = subparsers.add_parser(section, help="Sync dependencies and regenerate encore.lock")
    sync_parser.add_argument("--update", action="store_true", help="Pull latest changes for git dependencies")
    return (section, handle_sync)


def handle_sync(args: Namespace):
    cwd = Path().resolve()
    console = Console(highlight=False)
    resolved = sync_dependencies(cwd, update=args.update, ignore_errors=False)
    write_lockfile(cwd, resolved)
    console.print(f"Synced {len(resolved)} packages -> encore.lock")

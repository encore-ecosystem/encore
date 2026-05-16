from argparse import Namespace
from pathlib import Path
from typing import Callable

from encore.modes.build import update_dependencies


def add_update_parser(subparsers) -> tuple[str, Callable]:
    section = "update"
    _update_parser = subparsers.add_parser(section, help="Update all refrains")
    return (section, handle_update)


def handle_update(args: Namespace):
    cwd = Path().resolve()
    update_dependencies(cwd)

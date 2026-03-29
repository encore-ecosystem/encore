import argparse
import sys
from typing import Callable

from encore import modes

sys.setrecursionlimit(150)
MODES = [
    modes.add_init_parser,
    modes.add_build_parser,
]


def main():
    main_parser = argparse.ArgumentParser(prog="encore", description="Encore compiler")
    subparsers = main_parser.add_subparsers(dest="command", required=True, help="Available commands")

    dispatcher: dict[str, Callable] = {}
    for parser in MODES:
        name, handler = parser(subparsers)
        dispatcher[name] = handler

    args = main_parser.parse_args()
    if handler := dispatcher.get(args.command, None):
        handler(args)
    else:
        print(f"Unknown mode: {args.command}")

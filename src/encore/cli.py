import argparse
from typing import Callable

from encore import __version__, modes
from encore.utils.diagnostics import render_diagnostic

MODES = [
    # modes.add_add_parser,
    modes.add_init_parser,
    modes.add_lsp_parser,
    modes.add_install_parser,
    modes.add_build_parser,
    modes.add_run_parser,
    modes.add_memcheck_parser,
    # modes.add_sync_parser,
    modes.add_test_parser,
    # modes.add_update_parser,
]


def main():
    main_parser = argparse.ArgumentParser(prog="encore", description="Encore compiler")
    main_parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = main_parser.add_subparsers(dest="command", required=True, help="Available commands")

    dispatcher: dict[str, Callable] = {}
    for parser in MODES:
        name, handler = parser(subparsers)
        dispatcher[name] = handler

    args = main_parser.parse_args()
    try:
        if handler := dispatcher.get(args.command, None):
            handler(args)
        else:
            print(f"Unknown mode: {args.command}")
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(render_diagnostic(exc))
        raise SystemExit(1)

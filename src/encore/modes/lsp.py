from argparse import Namespace
from typing import Callable

from encore.lsp import run_stdio_server


def add_lsp_parser(subparsers) -> tuple[str, Callable]:
    section = "lsp"
    parser = subparsers.add_parser(section, help="Run Encore language server over stdio")
    parser.add_argument("--stdio", action="store_true", default=True, help="Run over stdio")
    return (section, handle_lsp)


def handle_lsp(_args: Namespace):
    raise SystemExit(run_stdio_server())

from argparse import REMAINDER, Namespace
from pathlib import Path
from typing import Callable

from encore.modes.build import (
    add_build_options,
    build_project,
)


def add_run_parser(subparsers) -> tuple[str, Callable]:
    section = "run"
    run_parser = subparsers.add_parser(section, help="Build and run a project")
    add_build_options(run_parser)
    run_parser.add_argument("program_args", nargs=REMAINDER, help="Arguments passed to executable")
    return (section, handle_run)


def handle_run(args: Namespace):
    cwd = Path().resolve()
    outputs = build_project(cwd, None, None)
    _, executable_path = outputs[0]
    program_args = args.program_args[1:] if args.program_args[:1] == ["--"] else args.program_args
    raise SystemExit(run_binary(executable_path, program_args))

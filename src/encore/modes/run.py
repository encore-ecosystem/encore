from argparse import REMAINDER, Namespace
from pathlib import Path
from typing import Callable

from ehir import Refrain

from encore.modes.build import (
    AVAILABLE_BACKENDS,
    AVAILABLE_OPTPROFILES,
    build_project,
    resolve_project_target_type,
    run_binary,
)


def add_run_parser(subparsers) -> tuple[str, Callable]:
    section = "run"
    run_parser = subparsers.add_parser(section, help="Build and run a project")
    run_parser.add_argument(
        "--backend", default="llvm", choices=set(AVAILABLE_BACKENDS.keys()), help="EHIR Compiler Backend"
    )
    run_parser.add_argument(
        "--profile", default="debug", choices=set(AVAILABLE_OPTPROFILES.keys()), help="Optimization profile"
    )
    run_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    run_parser.add_argument("program_args", nargs=REMAINDER, help="Arguments passed to executable")
    return (section, handle_run)


def handle_run(args: Namespace):
    cwd = Path().resolve()
    if resolve_project_target_type(cwd) != Refrain.TargetType.EXECUTABLE:
        raise RuntimeError("run is only available for executable projects")
    outputs = build_project(cwd, args.backend, args.profile, no_cache=args.no_cache)
    _, executable_path = outputs[0]
    program_args = args.program_args[1:] if args.program_args[:1] == ["--"] else args.program_args
    raise SystemExit(run_binary(executable_path, program_args))

import shutil
import subprocess
from argparse import REMAINDER, Namespace
from pathlib import Path
from typing import Callable

from encore.modes.build import (
    add_build_options,
    build_project,
)


def add_memcheck_parser(subparsers) -> tuple[str, Callable]:
    section = "memcheck"
    parser = subparsers.add_parser(section, help="Build and run an executable under Valgrind Memcheck")
    add_build_options(parser)
    parser.add_argument(
        "--valgrind",
        default="valgrind",
        help="Path to valgrind executable.",
    )
    parser.add_argument(
        "--error-exitcode",
        type=int,
        default=99,
        help="Exit code used when Valgrind reports memory errors or selected leaks.",
    )
    parser.add_argument(
        "--leak-kinds",
        default="definite,possible",
        help="Leak kinds that should fail the command.",
    )
    parser.add_argument(
        "--no-track-origins",
        action="store_true",
        help="Disable Valgrind origin tracking for faster runs.",
    )
    parser.add_argument("program_args", nargs=REMAINDER, help="Arguments passed to executable")
    return (section, handle_memcheck)


def handle_memcheck(args: Namespace):
    cwd = Path().resolve()
    if resolve_project_target_type(cwd) != Refrain.TargetType.EXECUTABLE:
        raise RuntimeError("memcheck is only available for executable projects")

    valgrind = shutil.which(args.valgrind)
    if valgrind is None:
        raise RuntimeError(
            "Valgrind is not installed or not found in PATH. Install valgrind or pass --valgrind /path/to/valgrind."
        )

    outputs = build_project(
        cwd,
        args.backend,
        resolve_build_profile(args),
        no_cache=args.no_cache,
        cfg_overrides=args.cfg,
        show_status=True,
        profile_timings=profile_timings_enabled(args),
    )
    _, executable_path = outputs[0]
    program_args = args.program_args[1:] if args.program_args[:1] == ["--"] else args.program_args

    cmd = [
        valgrind,
        "--leak-check=full",
        "--show-leak-kinds=all",
        f"--errors-for-leak-kinds={args.leak_kinds}",
        f"--error-exitcode={args.error_exitcode}",
    ]
    if not args.no_track_origins:
        cmd.append("--track-origins=yes")
    cmd.extend([str(executable_path), *program_args])

    result = subprocess.run(cmd, check=False)
    raise SystemExit(result.returncode)

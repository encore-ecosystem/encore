from argparse import Namespace
from pathlib import Path
from typing import Callable

from ehir_llvm_backend.optimizer import OptimizationProfile

from encore.compiler import EncoreCompiler
from encore.compiler.compiler import CompiledRefrain

AVAILABLE_BACKENDS = ["llvm"]
AVAILABLE_OPTPROFILES = [OptimizationProfile.debug, OptimizationProfile.release, OptimizationProfile.extreme]
PROFILE_TIMINGS_SENTINEL = "timings"
_ACTIVE_BUILD_SCRIPTS: set[Path] = set()


def add_build_parser(subparsers) -> tuple[str, Callable]:
    section = "build"
    build_parser = subparsers.add_parser(section, help="Build a project")
    add_build_options(build_parser)
    return (section, handle_build)


def add_build_options(parser) -> None:
    parser.add_argument("--release", action="store_true", help="Enable release optimizations")
    parser.add_argument("--backend", default="llvm", choices=set(AVAILABLE_BACKENDS), help="EHIR Compiler Backend")
    parser.add_argument(
        "--opt-profile",
        default=None,
        choices=set(AVAILABLE_OPTPROFILES),
        help="Optimization profile. Defaults to debug.",
    )
    parser.add_argument(
        "--profile",
        nargs="?",
        const=PROFILE_TIMINGS_SENTINEL,
        default=None,
        choices={*AVAILABLE_OPTPROFILES, PROFILE_TIMINGS_SENTINEL},
        help=(
            "Enable compiler timing profile when passed without a value. "
            "For compatibility, --profile debug|release|extreme still selects the optimization profile."
        ),
    )
    parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )


def handle_build(args: Namespace):
    cwd = Path().resolve()
    build_project(path=cwd, profile=OptimizationProfile.debug, show_status=True)


def build_project(
    path: Path,
    profile: OptimizationProfile,
    show_status: bool = False,
) -> list[CompiledRefrain]:
    compiler = EncoreCompiler()
    compiler.add_compile_target(path)
    return compiler.compile_all_targets()

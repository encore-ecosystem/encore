from argparse import Namespace
from pathlib import Path
import subprocess
from typing import Callable

from ehir_llvm_backend.optimizer import OptimizationProfile

from encore.compiler import EncoreCompiler

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
    build_project(
        path=cwd,
        backend=args.backend,
        profile=resolve_build_profile(args),
        no_cache=args.no_cache,
        cfg_overrides=args.cfg,
        show_status=True,
        profile_timings=profile_timings_enabled(args),
    )


def build_project(
    path: Path,
    backend: str | None = "llvm",
    profile: OptimizationProfile | str | None = OptimizationProfile.debug,
    show_status: bool = False,
    **_unused,
) -> list[tuple[str, Path]]:
    if backend not in (None, "llvm"):
        raise RuntimeError(f"Unsupported backend: {backend}")
    compiler = EncoreCompiler()
    compiler.add_compile_target(path)
    compiled = compiler.compile_all_targets()
    target_names = {target.name for target in compiler.targets}
    outputs = [(item.refrain.name, item.output_path) for item in compiled]
    return [
        *[item for item in outputs if item[0] in target_names],
        *[item for item in outputs if item[0] not in target_names],
    ]


def run_binary(executable_path: Path, program_args: list[str]) -> int:
    result = subprocess.run([str(executable_path), *program_args], check=False)
    return result.returncode


def resolve_build_profile(args: Namespace) -> OptimizationProfile:
    if args.profile in {OptimizationProfile.debug, OptimizationProfile.release, OptimizationProfile.extreme}:
        return args.profile
    if args.release:
        return OptimizationProfile.release
    if args.opt_profile is not None:
        return args.opt_profile
    return OptimizationProfile.debug


def profile_timings_enabled(args: Namespace) -> bool:
    return args.profile == PROFILE_TIMINGS_SENTINEL

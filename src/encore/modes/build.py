import shutil
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Callable

import ehir
from ehir.backend import OptProfile
from ehir_llvm_backend import EHIR_LLVM_Backend

from encore.translator.project_tree import ProjectTree
from encore.translator.translator import Translator
from encore.utils.manifest import ProjectManifest

AVAILABLE_BACKENDS = {"llvm": EHIR_LLVM_Backend}
AVAILABLE_OPTPROFILES = {
    "debug": OptProfile.debug,
    "release": OptProfile.release,
    "extreme": OptProfile.extreme,
}


def add_build_parser(subparsers) -> tuple[str, Callable]:
    section = "build"
    build_parser = subparsers.add_parser(section, help="Build a project")
    build_parser.add_argument("--release", action="store_true", help="Enable release optimizations")
    build_parser.add_argument(
        "--backend", default="llvm", choices=set(AVAILABLE_BACKENDS.keys()), help="EHIR Compiler Backend"
    )
    build_parser.add_argument(
        "--profile", default="debug", choices=set(AVAILABLE_OPTPROFILES.keys()), help="Optimization profile"
    )
    return (section, handle_build)


def handle_build(args: Namespace):
    cwd = Path().resolve()

    manifest_path = cwd / ProjectManifest.default_filename()
    if not manifest_path.exists():
        print("Project is not initialized")
        exit(-1)

    with manifest_path.open("r") as f:
        manifest = ProjectManifest(**tomllib.loads(f.read()))

    project_tree = ProjectTree(
        manifest=manifest, profile=AVAILABLE_OPTPROFILES[args.profile], backend=AVAILABLE_BACKENDS[args.backend]()
    )
    project_tree.compile(entrypoint=cwd / "src" / "main.enq")

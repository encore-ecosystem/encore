import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Callable

import git
from ehir.backend import EHIR_Backend
from ehir.compiler import EHIR_ProjectCompiler, Target
from ehir_llvm_backend import EHIR_LLVM_Backend

from encore import PROJECT_ROOT
from encore.frontend import EHIR_EncoreFrontend
from encore.utils.manifest import ProjectManifest

AVAILABLE_BACKENDS = {"llvm": EHIR_LLVM_Backend}
AVAILABLE_OPTPROFILES = {
    "debug": EHIR_Backend.OptProfile.debug,
    "release": EHIR_Backend.OptProfile.release,
    "extreme": EHIR_Backend.OptProfile.extreme,
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

    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_EncoreFrontend(src_dir=cwd / "src"),
        backend=AVAILABLE_BACKENDS[args.backend](
            target_dir=cwd / "target", opt_profile=AVAILABLE_OPTPROFILES[args.profile]
        ),
    )

    for dependency in manifest.project.dependencies:
        target = get_target_dependency(dependency)
        compiler.add_target_to_build(target)

    compiler.add_target_to_build(Target(module_id=(cwd / "src" / "main.enq").__str__()))
    compiler.compile_all_targets()


def get_target_dependency(dep: str) -> Target:
    from git import Repo

    from encore import ENCORE_CACHE_DIR

    ENCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if dep.startswith("git@"):
        repo_url = dep.removeprefix("git@")
        org, repo_name = repo_url.split("/")[-2:]
        path = ENCORE_CACHE_DIR / "git" / org / repo_name
        path.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(url=repo_url, to_path=path)

    elif dep.startswith("path@"):
        path = dep.removeprefix("path@")

    else:
        raise RuntimeError(f"Unable to load dependency: {dep}")

    return Target(module_id=path.__str__(), type=Target.TargetType.RAW)

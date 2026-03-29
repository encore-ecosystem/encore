import subprocess
import tomllib
from argparse import Namespace
from pathlib import Path
from typing import Callable

from ehir import Refrain
from ehir.backend import EHIR_Backend
from ehir.compiler import EHIR_ProjectCompiler
from ehir_llvm_backend import EHIR_LLVM_Backend

from encore.frontend import EHIR_EncoreFrontend
from encore.utils.manifest import ProjectManifest, ProjectTarget

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

    compiler = create_compiler(cwd, args.backend, args.profile)
    _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd))
    compiler.compile_all()


def create_compiler(cwd: Path, backend: str, profile: str) -> EHIR_ProjectCompiler:
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_EncoreFrontend(src_dir=cwd / "src"),
        backend=AVAILABLE_BACKENDS[backend](target_dir=cwd / "target", opt_profile=AVAILABLE_OPTPROFILES[profile]),
    )
    return compiler


def load_manifest(path: Path) -> ProjectManifest:
    manifest_path = path / ProjectManifest.default_filename()
    if not manifest_path.exists():
        raise RuntimeError(f"Project {path} is not initialized")

    with manifest_path.open("rb") as f:
        return ProjectManifest(**tomllib.load(f))


def save_manifest(path: Path, manifest: ProjectManifest):
    import toml

    manifest_path = path / ProjectManifest.default_filename()
    with manifest_path.open("w") as f:
        f.write(toml.dumps(manifest.model_dump()))


def _resolve_dependency(dep: str, update: bool = False) -> Path:
    from git import Repo

    from encore import ENCORE_CACHE_DIR

    ENCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if dep.startswith("git@"):
        repo_url = dep.removeprefix("git@")
        org, repo_name = repo_url.split("/")[-2:]
        path = ENCORE_CACHE_DIR / "git" / org / repo_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not (path / ".git").exists():
            Repo.clone_from(url=repo_url, to_path=path)
        elif update:
            Repo(path).remotes.origin.pull()

    elif dep.startswith("path@"):
        path = Path(dep.removeprefix("path@")).resolve()

    else:
        raise RuntimeError(f"Unable to load dependency: {dep}")

    return path


def _load_refrain(
    compiler: EHIR_ProjectCompiler, path: Path, type: Refrain.TargetType = Refrain.TargetType.OBJECT
) -> Refrain:
    manifest = load_manifest(path)

    for dependency in manifest.project.dependencies:
        _dep_path = _resolve_dependency(dependency)
        _load_refrain(compiler, _dep_path, Refrain.TargetType.OBJECT)

    ref = Refrain(
        name=manifest.project.name,
        path=path,
        type=type,
    )
    compiler.add_refrain_to_build(ref)
    return ref


def infer_project_target_type(cwd: Path) -> Refrain.TargetType:
    src_dir = cwd / "src"
    has_main = (src_dir / "main.enq").exists()
    has_lib = (src_dir / "lib.enq").exists()

    if has_main:
        return Refrain.TargetType.EXECUTABLE
    if has_lib:
        return Refrain.TargetType.STATIC_LIB
    raise RuntimeError(f"Unable to determine project target type in {cwd}: expected src/main.enq or src/lib.enq")


def resolve_project_target_type(cwd: Path) -> Refrain.TargetType:
    manifest = load_manifest(cwd)
    match manifest.project.target:
        case ProjectTarget.AUTO:
            return infer_project_target_type(cwd)
        case ProjectTarget.EXECUTABLE:
            return Refrain.TargetType.EXECUTABLE
        case ProjectTarget.STATIC_LIB:
            return Refrain.TargetType.STATIC_LIB
        case ProjectTarget.SHARED_LIB:
            raise NotImplementedError("shared_lib target is declared in encore.toml, but is not supported yet")
    raise RuntimeError(f"Unknown project target type: {manifest.project.target}")


def build_project(cwd: Path, backend: str, profile: str) -> list[tuple[str, Path]]:
    compiler = create_compiler(cwd, backend, profile)
    entry_ref = _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd))
    outputs = compiler.compile_all()
    outputs_by_name = dict(outputs)
    return [(entry_ref.name, outputs_by_name[entry_ref.name]), *[(n, p) for n, p in outputs if n != entry_ref.name]]


def run_binary(binary_path: Path, args: list[str]) -> int:
    result = subprocess.run([str(binary_path), *args], check=False)
    return result.returncode


def update_dependencies(path: Path):
    manifest = load_manifest(path)
    for dependency in manifest.project.dependencies:
        dep_path = _resolve_dependency(dependency, update=True)
        dep_manifest = dep_path / ProjectManifest.default_filename()
        if dep_manifest.exists():
            update_dependencies(dep_path)

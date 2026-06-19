import json
import os
import subprocess
import tomllib
from argparse import Namespace
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ehir.compiler import EHIR_ProjectCompiler
from ehir_llvm_backend.optimizer import OptimizationProfile
from git import Repo
from rich.console import Console, Group
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from encore.compiler import EncoreCompiler
from encore.utils.manifest import NativeSection, ProjectManifest, ProjectTarget

AVAILABLE_BACKENDS = ["llvm"]
AVAILABLE_OPTPROFILES = [OptimizationProfile.debug, OptimizationProfile.release, OptimizationProfile.extreme]
PROFILE_TIMINGS_SENTINEL = "timings"
SYSTEM_CORE_REF = "sys@core"
_ACTIVE_BUILD_SCRIPTS: set[Path] = set()
_BUILD_SCRIPT_METADATA_CACHE: dict[tuple[object, ...], NativeSection] = {}


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
    build_project(profile=OptimizationProfile.debug, show_status=True)


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


def _resolve_dependency(dep: str, base_path: Path, update: bool = False) -> Path:
    from encore import ENCORE_CACHE_DIR

    ENCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if dep == SYSTEM_CORE_REF:
        core_root = _resolve_local_core_root(base_path)
        if core_root is None:
            raise RuntimeError("Unable to resolve system dependency 'core'")
        return core_root

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
        path = (base_path / dep.removeprefix("path@")).resolve()
        manifest_path = path / ProjectManifest.default_filename()
        if not manifest_path.exists():
            parts = path.parts
            if "index" in parts:
                pkg_name = path.name
                mapped_dep = f"git@https://github.com/encore-language-index/{pkg_name}"
                return _resolve_dependency(mapped_dep, base_path, update=update)

    else:
        raise RuntimeError(f"Unable to load dependency: {dep}")

    return path


# def _run_build_script(
#     *,
#     manifest: ProjectManifest,
#     project_path: Path,
#     script_path: Path,
# ) -> NativeSection:
#     import toml

#     target_dir = project_path / "target" / build_ctx.profile / "build"
#     script_workspace = _build_script_workspace_name(
#         manifest=manifest,
#         project_path=project_path,
#         script_path=script_path,
#         cfg_environment=cfg_environment,
#         build_ctx=build_ctx,
#     )
#     script_dir = target_dir / "scripts" / script_workspace
#     src_dir = script_dir / "src"
#     out_dir = target_dir / "out" / script_workspace
#     meta_path = out_dir / "build-meta.json"

#     src_dir.mkdir(parents=True, exist_ok=True)
#     out_dir.mkdir(parents=True, exist_ok=True)
#     if meta_path.exists():
#         meta_path.unlink()

#     src_main = src_dir / "main.enq"
#     src_main.write_text(script_path.read_text(), encoding="utf-8")

#     script_manifest: dict[str, Any] = {
#         "project": {
#             "name": f"{manifest.project.name}__build_script",
#             "target": "executable",
#             "version": "0.0.0",
#             "description": "",
#             "readme": "README.md",
#             "licence": "MIT",
#             "dependencies": [_rewrite_build_dependency(dep, project_path) for dep in manifest.project.dependencies],
#         }
#     }
#     core_root = _resolve_local_core_root(project_path)
#     if manifest.project.name == "core" and core_root is not None:
#         runtime_c = (core_root / "runtime.c").resolve()
#         if runtime_c.exists():
#             script_manifest["native"] = {
#                 "libraries": [
#                     {
#                         "name": "encore_core_native_for_build_script",
#                         "path": runtime_c.as_posix(),
#                     }
#                 ]
#             }
#     (script_dir / "encore.toml").write_text(toml.dumps(script_manifest), encoding="utf-8")
#     (script_dir / "README.md").write_text("# build script\n", encoding="utf-8")

#     _ACTIVE_BUILD_SCRIPTS.add(project_path.resolve())
#     try:
#         script_compiler = create_compiler(
#             script_dir,
#             build_ctx.backend,
#             build_ctx.profile,
#             no_cache=build_ctx.no_cache,
#             cfg_overrides=list(build_ctx.cfg_overrides),
#             profile_timings=build_ctx.profile_timings,
#         )
#         _inject_mandatory_core_dependency(script_compiler, script_dir, build_ctx)
#         script_ref = _load_refrain(
#             script_compiler,
#             script_dir,
#             type=Refrain.TargetType.EXECUTABLE,
#             build_ctx=build_ctx,
#         )
#         script_outputs = script_compiler.compile_all()
#         script_binary = dict(script_outputs)[script_ref.name]

#         script_args = [
#             meta_path.resolve().as_posix(),
#             project_path.resolve().as_posix(),
#             script_path.resolve().as_posix(),
#             build_ctx.profile,
#             build_ctx.backend,
#             json.dumps(
#                 {
#                     "flags": sorted(cfg_environment.flags),
#                     "values": dict(sorted(cfg_environment.values.items())),
#                 }
#             ),
#         ]
#         exit_code = run_binary(script_binary, script_args)
#         if exit_code != 0:
#             raise RuntimeError(f"build.enq failed for '{manifest.project.name}' with exit code {exit_code}")
#         if not meta_path.exists():
#             raise RuntimeError(
#                 f"build.enq for '{manifest.project.name}' did not produce build metadata at {meta_path.as_posix()}"
#             )

#         data = json.loads(meta_path.read_text(encoding="utf-8"))
#         native_payload = data.get("native")
#         if native_payload is None:
#             raise RuntimeError(f"build.enq metadata for '{manifest.project.name}' must include 'native' section")
#         if not isinstance(native_payload, dict):
#             raise RuntimeError(
#                 f"build.enq metadata 'native' section must be a table, got: {type(native_payload).__name__}"
#             )

#         return NativeSection(**native_payload)
#     finally:
#         _ACTIVE_BUILD_SCRIPTS.discard(project_path.resolve())


def build_project(
    profile: OptimizationProfile,
    show_status: bool = False,
) -> list[tuple[str, Path]]:
    # entry_ref = _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd), build_ctx=build_ctx)
    # if show_status:
    #     with _BuildLiveStatus(compiler):
    #         outputs = compiler.compile_all()
    # else:
    #     outputs = compiler.compile_all()
    cwd = Path().resolve()
    compiler = EncoreCompiler(src_dir=cwd)
    outputs = compiler.compile_all()
    outputs_by_name = dict(outputs)
    return [(entry_ref.name, outputs_by_name[entry_ref.name]), *[(n, p) for n, p in outputs if n != entry_ref.name]]

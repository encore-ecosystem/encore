import os
import subprocess
import tomllib
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ehir.backend import EHIR_Backend
from ehir.compiler import EHIR_ProjectCompiler
from git import Repo
from rich.console import Console, Group
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from ehir import Refrain
from encore.frontend import EHIR_EncoreFrontend, format_module_reflection
from encore.utils.manifest import ProjectManifest, ProjectTarget

AVAILABLE_OPTPROFILES = {
    "debug": EHIR_Backend.OptProfile.debug,
    "release": EHIR_Backend.OptProfile.release,
    "extreme": EHIR_Backend.OptProfile.extreme,
}
AVAILABLE_BACKENDS = ("llvm",)
SYSTEM_CORE_REF = "sys@core"


@dataclass
class _BuildLiveStatus:
    compiler: EHIR_ProjectCompiler
    _current_refrain: str = ""
    _current_file: str = ""
    _live: Live | None = None
    _console: Console = field(init=False, repr=False, default_factory=lambda: Console(highlight=False))

    def __enter__(self):
        self._live = Live(self._render(), console=self._console, refresh_per_second=12, transient=True)
        self._live.__enter__()
        self.compiler.on_refrain = self.set_refrain
        frontend = self.compiler.frontend
        if isinstance(frontend, EHIR_EncoreFrontend):
            frontend.on_module_load = self.set_file
        return self

    def __exit__(self, exc_type, exc, tb):
        self.compiler.on_refrain = None
        frontend = self.compiler.frontend
        if isinstance(frontend, EHIR_EncoreFrontend):
            frontend.on_module_load = None
        assert self._live is not None
        return self._live.__exit__(exc_type, exc, tb)

    def set_refrain(self, refrain: Refrain) -> None:
        self._current_refrain = refrain.name
        self._current_file = ""
        self._refresh()

    def set_file(self, module_id: Path) -> None:
        self._current_file = self._format_module_path(module_id)
        self._refresh()

    def _refresh(self) -> None:
        if self._live is None:
            return
        self._live.update(self._render())

    def _render(self):
        return Group(
            Spinner("dots", text=self._current_refrain),
            Text(self._current_file or " ", style="dim"),
        )

    def _format_module_path(self, module_id: Path) -> str:
        module_id = module_id.resolve()
        for refrain in sorted(self.compiler.refrains.values(), key=lambda ref: len(ref.path.parts), reverse=True):
            src_root = (refrain.path / "src").resolve()
            try:
                return module_id.relative_to(src_root).as_posix()
            except ValueError:
                pass

            tests_root = (refrain.path / "tests").resolve()
            try:
                rel = module_id.relative_to(tests_root).as_posix()
                return f"tests/{rel}"
            except ValueError:
                continue
        return module_id.name


def add_build_parser(subparsers) -> tuple[str, Callable]:
    section = "build"
    build_parser = subparsers.add_parser(section, help="Build a project")
    build_parser.add_argument("--release", action="store_true", help="Enable release optimizations")
    build_parser.add_argument(
        "--backend", default="llvm", choices=set(AVAILABLE_BACKENDS), help="EHIR Compiler Backend"
    )
    build_parser.add_argument(
        "--profile", default="debug", choices=set(AVAILABLE_OPTPROFILES.keys()), help="Optimization profile"
    )
    build_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    return (section, handle_build)


def handle_build(args: Namespace):
    cwd = Path().resolve()

    compiler = create_compiler(cwd, args.backend, args.profile, no_cache=args.no_cache)
    _inject_mandatory_core_dependency(compiler, cwd)
    _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd))
    with _BuildLiveStatus(compiler):
        compiler.compile_all()
    _emit_reflection_artifacts(compiler)


def create_compiler(cwd: Path, backend: str, profile: str, *, no_cache: bool = False) -> EHIR_ProjectCompiler:
    backend_cls = _resolve_backend(backend)
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_EncoreFrontend(src_dir=cwd / "src"),
        backend=backend_cls(target_dir=cwd / "target", opt_profile=AVAILABLE_OPTPROFILES[profile]),
        use_cache=not no_cache,
    )
    return compiler


def _resolve_backend(name: str):
    if name == "llvm":
        from ehir_llvm_backend import EHIR_LLVM_Backend

        return EHIR_LLVM_Backend
    raise RuntimeError(f"Unknown backend: {name}")


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


def _resolve_local_core_root(project_root: Path) -> Path | None:
    from os import getenv

    from encore import ENCORE_CACHE_DIR, PROJECT_ROOT

    canonical_candidates = [
        (PROJECT_ROOT / "core").resolve(),
        (PROJECT_ROOT / "refrains" / "core").resolve(),
    ]
    for candidate in canonical_candidates:
        manifest_path = candidate / ProjectManifest.default_filename()
        if not manifest_path.exists():
            continue
        manifest = load_manifest(candidate)
        if manifest.project.name == "core":
            return candidate

    candidates: list[Path] = []
    for base in [project_root, *project_root.parents]:
        candidates.append(base / "refrains" / "core")
        candidates.append(base / "core")
        candidates.append(base / "encore" / "refrains" / "core")
        candidates.append(base / "encore" / "core")
    cwd = Path.cwd().resolve()
    for base in [cwd, *cwd.parents]:
        candidates.append(base / "refrains" / "core")
        candidates.append(base / "core")
        candidates.append(base / "encore" / "refrains" / "core")
        candidates.append(base / "encore" / "core")
    encore_home = getenv("ENCORE_HOME")
    if encore_home:
        base = Path(encore_home).expanduser().resolve()
        candidates.append(base / "refrains" / "core")
        candidates.append(base / "core")
    candidates.append(Path(__file__).resolve().parents[3] / "enc_future" / "refrains" / "core")
    candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "core")
    candidates.append(ENCORE_CACHE_DIR / "git" / "encore-language" / "encore-core")

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        manifest_path = candidate / ProjectManifest.default_filename()
        if not manifest_path.exists():
            continue
        manifest = load_manifest(candidate)
        if manifest.project.name == "core":
            return candidate

    return None


def _inject_mandatory_core_dependency(compiler: EHIR_ProjectCompiler, project_root: Path) -> None:
    manifest = load_manifest(project_root)
    if manifest.project.name == "core":
        return

    core_root = _resolve_local_core_root(project_root)
    if core_root is None:
        raise RuntimeError(
            "Unable to resolve mandatory dependency 'core'. "
            "Expected to find it in dependencies or as local 'refrains/core'."
        )

    _load_refrain(compiler, core_root, Refrain.TargetType.OBJECT)


def _load_refrain(
    compiler: EHIR_ProjectCompiler, path: Path, type: Refrain.TargetType = Refrain.TargetType.OBJECT
) -> Refrain:
    manifest = load_manifest(path)

    for dependency in manifest.project.dependencies:
        _dep_path = _resolve_dependency(dependency, path)
        _load_refrain(compiler, _dep_path, Refrain.TargetType.OBJECT)

    ref = Refrain(
        name=manifest.project.name,
        path=path,
        type=type,
        merge_module_dirs=("modes",) if (path / "src" / "modes").exists() else (),
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


def build_project(cwd: Path, backend: str, profile: str, *, no_cache: bool = False) -> list[tuple[str, Path]]:
    compiler = create_compiler(cwd, backend, profile, no_cache=no_cache)
    _inject_mandatory_core_dependency(compiler, cwd)
    entry_ref = _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd))
    outputs = compiler.compile_all()
    _emit_reflection_artifacts(compiler)
    outputs_by_name = dict(outputs)
    return [(entry_ref.name, outputs_by_name[entry_ref.name]), *[(n, p) for n, p in outputs if n != entry_ref.name]]


def _emit_reflection_artifacts(compiler: EHIR_ProjectCompiler) -> None:
    frontend = compiler.frontend
    if not isinstance(frontend, EHIR_EncoreFrontend):
        return

    for module_id, reflection in frontend._reflection_cache.items():
        artifact_path = _reflection_artifact_path(compiler, Path(module_id))
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(format_module_reflection(reflection))


def _reflection_artifact_path(compiler: EHIR_ProjectCompiler, module_id: Path) -> Path:
    reflection_root = compiler.backend.profile_path / "reflection"
    module_id = module_id.resolve()

    for refrain in sorted(compiler.refrains.values(), key=lambda ref: len(ref.path.parts), reverse=True):
        src_root = (refrain.path / "src").resolve()
        try:
            relative = module_id.relative_to(src_root)
            return (reflection_root / refrain.name / relative).with_suffix(".reflection.txt")
        except ValueError:
            pass

        tests_root = (refrain.path / "tests").resolve()
        try:
            relative = Path("tests") / module_id.relative_to(tests_root)
            return (reflection_root / refrain.name / relative).with_suffix(".reflection.txt")
        except ValueError:
            continue

    return (reflection_root / module_id.name).with_suffix(".reflection.txt")


def run_binary(binary_path: Path, args: list[str]) -> int:
    result = subprocess.run([str(binary_path), *args], check=False)
    return result.returncode


def update_dependencies(path: Path):
    manifest = load_manifest(path)
    for dependency in manifest.project.dependencies:
        dep_path = _resolve_dependency(dependency, path, update=True)
        dep_manifest = dep_path / ProjectManifest.default_filename()
        if dep_manifest.exists():
            update_dependencies(dep_path)


def sync_dependencies(path: Path, *, update: bool = False, ignore_errors: bool = False) -> dict[str, dict[str, str]]:
    manifest = load_manifest(path)
    resolved: dict[str, dict[str, str]] = {}
    visited: set[Path] = set()

    def visit(project_path: Path) -> None:
        project_path = project_path.resolve()
        if project_path in visited:
            return
        visited.add(project_path)

        project_manifest = load_manifest(project_path)
        for dep_ref in project_manifest.project.dependencies:
            try:
                dep_path = _resolve_dependency(dep_ref, project_path, update=update)
                dep_manifest = load_manifest(dep_path)
            except Exception:
                if ignore_errors:
                    continue
                raise
            info: dict[str, str] = {
                "name": dep_manifest.project.name,
                "ref": _resolved_ref_for_lock(dep_ref, project_path, dep_path),
                "version": dep_manifest.project.version,
            }
            git_dir = dep_path / ".git"
            if git_dir.exists():
                try:
                    repo = Repo(dep_path)
                    info["commit"] = repo.head.commit.hexsha
                except Exception:
                    pass
            resolved[dep_manifest.project.name] = info
            try:
                visit(dep_path)
            except Exception:
                if not ignore_errors:
                    raise

    visit(path)
    if load_manifest(path).project.name != "core":
        core_root = _resolve_dependency(SYSTEM_CORE_REF, path, update=update)
        core_manifest = load_manifest(core_root)
        resolved.setdefault(
            core_manifest.project.name,
            {
                "name": core_manifest.project.name,
                "ref": SYSTEM_CORE_REF,
                "version": core_manifest.project.version,
            },
        )
    return resolved


def _resolved_ref_for_lock(dep_ref: str, project_path: Path, dep_path: Path) -> str:
    if dep_ref.startswith("git@"):
        return dep_ref

    if dep_ref.startswith("path@"):
        requested_path = (project_path / dep_ref.removeprefix("path@")).resolve()
        if requested_path == dep_path.resolve():
            return _path_ref_for_lock(project_path, dep_path)

        # Legacy path@index/* fallback: persist effective git ref in lock.
        if "index" in requested_path.parts:
            pkg_name = requested_path.name
            return f"git@https://github.com/encore-language-index/{pkg_name}"

    return dep_ref


def _path_ref_for_lock(base_path: Path, target_path: Path) -> str:
    try:
        rel = target_path.resolve().relative_to(base_path.resolve())
        return f"path@{rel.as_posix()}"
    except ValueError:
        pass
    relative = Path(os.path.relpath(target_path.resolve(), base_path.resolve()))
    return f"path@{relative.as_posix()}"


def write_lockfile(path: Path, resolved: dict[str, dict[str, str]]) -> None:
    import toml

    lock_path = path / "encore.lock"
    packages = [resolved[name] for name in sorted(resolved)]
    lock_data = {"version": 1, "packages": packages}
    lock_path.write_text(toml.dumps(lock_data))

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

from encore.frontend import EHIR_EncoreFrontend
from encore.utils.manifest import NativeSection, ProjectManifest, ProjectTarget

AVAILABLE_BACKENDS = {"llvm": [OptimizationProfile.debug, OptimizationProfile.release, OptimizationProfile.extreme]}
PROFILE_TIMINGS_SENTINEL = "timings"
SYSTEM_CORE_REF = "sys@core"
_ACTIVE_BUILD_SCRIPTS: set[Path] = set()
_BUILD_SCRIPT_METADATA_CACHE: dict[tuple[object, ...], NativeSection] = {}


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


@dataclass(frozen=True)
class _BuildScriptContext:
    backend: str
    profile: str
    no_cache: bool
    cfg_overrides: tuple[str, ...]
    profile_timings: bool = False
    workspace_suffix: str | None = None


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
        choices=set(AVAILABLE_OPTPROFILES.keys()),
        help="Optimization profile. Defaults to debug.",
    )
    parser.add_argument(
        "--profile",
        nargs="?",
        const=PROFILE_TIMINGS_SENTINEL,
        default=None,
        choices={*AVAILABLE_OPTPROFILES.keys(), PROFILE_TIMINGS_SENTINEL},
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
        cwd,
        args.backend,
        resolve_build_profile(args),
        no_cache=args.no_cache,
        cfg_overrides=args.cfg,
        show_status=True,
        profile_timings=profile_timings_enabled(args),
    )


def resolve_build_profile(args: Namespace) -> str:
    if getattr(args, "release", False):
        return "release"
    if getattr(args, "opt_profile", None) is not None:
        return args.opt_profile
    legacy_profile = getattr(args, "profile", None)
    if legacy_profile in AVAILABLE_OPTPROFILES:
        return legacy_profile
    return "debug"


def profile_timings_enabled(args: Namespace) -> bool:
    return getattr(args, "profile", None) == PROFILE_TIMINGS_SENTINEL


def create_compiler(
    cwd: Path,
    backend: str,
    profile: str,
    *,
    no_cache: bool = False,
    cfg_overrides: list[str] | None = None,
    target_dir: Path | None = None,
    cache_dir: Path | None = None,
    profile_timings: bool = False,
) -> EHIR_ProjectCompiler:
    backend_cls = _resolve_backend(backend)
    cfg_environment = default_cfg_environment(backend=backend, extra=cfg_overrides or [])
    compiler = EHIR_ProjectCompiler(
        frontend=EHIR_EncoreFrontend(src_dir=cwd / "src", cfg_environment=cfg_environment),
        backend=backend_cls(target_dir=target_dir or cwd / "target", opt_profile=AVAILABLE_OPTPROFILES[profile]),
        cache_dir=cache_dir,
        use_cache=not no_cache,
        cfg_environment=cfg_environment,
        profile_timings=profile_timings,
    )
    return compiler


def print_profile_report(compiler: EHIR_ProjectCompiler) -> None:
    records = compiler.profile_records
    if not records:
        return

    console = Console(highlight=False)
    stage_totals: dict[str, float] = {}
    for record in records:
        stage_totals[record.stage] = stage_totals.get(record.stage, 0.0) + record.seconds

    total = sum(record.seconds for record in records)
    console.print(f"\n[bold]Compiler profile[/bold] total measured: {total:.3f}s")

    stage_table = Table(title="Stage totals")
    stage_table.add_column("stage")
    stage_table.add_column("time", justify="right")
    stage_table.add_column("%", justify="right")
    for stage, seconds in sorted(stage_totals.items(), key=lambda item: item[1], reverse=True):
        percent = (seconds / total * 100.0) if total > 0 else 0.0
        stage_table.add_row(stage, f"{seconds:.3f}s", f"{percent:.1f}%")
    console.print(stage_table)

    slowest_table = Table(title="Slowest stage invocations")
    slowest_table.add_column("refrain")
    slowest_table.add_column("stage")
    slowest_table.add_column("time", justify="right")
    slowest_table.add_column("detail", overflow="fold")
    for record in sorted(records, key=lambda item: item.seconds, reverse=True)[:20]:
        slowest_table.add_row(record.refrain, record.stage, f"{record.seconds:.3f}s", record.detail)
    console.print(slowest_table)


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


def _inject_mandatory_core_dependency(
    compiler: EHIR_ProjectCompiler,
    project_root: Path,
    build_ctx: _BuildScriptContext,
) -> None:
    manifest = load_manifest(project_root)
    if manifest.project.name == "core":
        return

    core_root = _resolve_local_core_root(project_root)
    if core_root is None:
        raise RuntimeError(
            "Unable to resolve mandatory dependency 'core'. "
            "Expected to find it in dependencies or as local 'refrains/core'."
        )

    _load_refrain(compiler, core_root, Refrain.TargetType.OBJECT, build_ctx=build_ctx)


def _load_refrain(
    compiler: EHIR_ProjectCompiler,
    path: Path,
    type: Refrain.TargetType = Refrain.TargetType.OBJECT,
    *,
    build_ctx: _BuildScriptContext,
    name: str | None = None,
    entry_root: str | None = None,
    entrypoint: str | None = None,
) -> Refrain:
    manifest = load_manifest(path)

    for dependency in manifest.project.dependencies:
        _dep_path = _resolve_dependency(dependency, path)
        _load_refrain(compiler, _dep_path, Refrain.TargetType.OBJECT, build_ctx=build_ctx)

    native_libraries = _native_libraries_from_manifest(manifest, path, compiler.cfg_environment)
    native_libraries.extend(_native_libraries_from_build_script(manifest, path, compiler.cfg_environment, build_ctx))
    native_libraries = _materialize_native_sources(native_libraries, path, build_ctx.profile)

    ref = Refrain(
        name=name or manifest.project.name,
        path=path,
        type=type,
        entry_root=entry_root or "src",
        entrypoint=entrypoint,
        native_libraries=native_libraries,
    )
    compiler.add_refrain_to_build(ref)
    return ref


def _native_libraries_from_manifest(
    manifest: ProjectManifest,
    project_path: Path,
    cfg_environment: CfgEnvironment,
) -> list[NativeLibrary]:
    return _native_libraries_from_native_section(manifest.project.name, manifest.native, project_path, cfg_environment)


def _native_libraries_from_native_section(
    project_name: str,
    native: NativeSection,
    project_path: Path,
    cfg_environment: CfgEnvironment,
) -> list[NativeLibrary]:
    result: list[NativeLibrary] = []

    if native.search_paths or native.frameworks or native.link_args:
        result.append(
            NativeLibrary(
                name=f"{project_name}::native",
                kind="link_args",
                search_paths=tuple(_resolve_native_path(project_path, path) for path in native.search_paths),
                frameworks=tuple(native.frameworks),
                link_args=tuple(native.link_args),
            )
        )

    for entry in native.libraries:
        if isinstance(entry, str):
            result.append(
                NativeLibrary(
                    name=entry,
                    search_paths=tuple(_resolve_native_path(project_path, path) for path in native.search_paths),
                    frameworks=tuple(native.frameworks),
                    link_args=tuple(native.link_args),
                )
            )
            continue

        if entry.cfg is not None and not cfg_matches(entry.cfg, cfg_environment):
            continue

        result.append(
            NativeLibrary(
                name=entry.name,
                kind=entry.kind,
                link_name=entry.link_name,
                path=_resolve_native_path(project_path, entry.path) if entry.path is not None else None,
                search_paths=tuple(
                    _resolve_native_path(project_path, path) for path in [*native.search_paths, *entry.search_paths]
                ),
                frameworks=tuple([*native.frameworks, *entry.frameworks]),
                link_args=tuple([*native.link_args, *entry.link_args]),
                cfg=entry.cfg,
            )
        )
    return result


def _native_libraries_from_build_script(
    manifest: ProjectManifest,
    project_path: Path,
    cfg_environment: CfgEnvironment,
    build_ctx: _BuildScriptContext,
) -> list[NativeLibrary]:
    project_path = project_path.resolve()
    if project_path in _ACTIVE_BUILD_SCRIPTS:
        return []

    script_path = _resolve_build_script_path(manifest, project_path)
    if script_path is None:
        return []

    cache_key = _build_script_cache_key(manifest, project_path, script_path, cfg_environment, build_ctx)
    if cached := _BUILD_SCRIPT_METADATA_CACHE.get(cache_key):
        return _native_libraries_from_native_section(
            manifest.project.name,
            _clone_native_section(cached),
            project_path,
            cfg_environment,
        )
    if cached := _load_build_script_metadata_cache(project_path, build_ctx.profile, cache_key):
        _BUILD_SCRIPT_METADATA_CACHE[cache_key] = _clone_native_section(cached)
        return _native_libraries_from_native_section(
            manifest.project.name,
            cached,
            project_path,
            cfg_environment,
        )

    native = _run_build_script(
        manifest=manifest,
        project_path=project_path,
        script_path=script_path,
        cfg_environment=cfg_environment,
        build_ctx=build_ctx,
    )
    _BUILD_SCRIPT_METADATA_CACHE[cache_key] = _clone_native_section(native)
    _store_build_script_metadata_cache(project_path, build_ctx.profile, cache_key, native)
    return _native_libraries_from_native_section(manifest.project.name, native, project_path, cfg_environment)


def _clone_native_section(native: NativeSection) -> NativeSection:
    return NativeSection(**native.model_dump())


def _build_script_cache_key(
    manifest: ProjectManifest,
    project_path: Path,
    script_path: Path,
    cfg_environment: CfgEnvironment,
    build_ctx: _BuildScriptContext,
) -> tuple[object, ...]:
    digest = sha1(usedforsecurity=False)
    digest.update(script_path.read_bytes())
    digest.update(json.dumps(manifest.model_dump(mode="json"), sort_keys=True).encode())
    return (
        project_path.resolve().as_posix(),
        script_path.resolve().as_posix(),
        build_ctx.backend,
        build_ctx.profile,
        tuple(sorted(cfg_environment.flags)),
        tuple((key, cfg_environment.values[key]) for key in sorted(cfg_environment.values)),
        digest.hexdigest(),
    )


def _build_script_metadata_cache_path(
    project_path: Path,
    profile: str,
    cache_key: tuple[object, ...],
) -> Path:
    digest = sha1(repr(cache_key).encode(), usedforsecurity=False).hexdigest()
    return project_path / "target" / profile / "build" / "metadata" / f"{digest}.json"


def _load_build_script_metadata_cache(
    project_path: Path,
    profile: str,
    cache_key: tuple[object, ...],
) -> NativeSection | None:
    cache_path = _build_script_metadata_cache_path(project_path, profile, cache_key)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return NativeSection(**payload)
    except Exception:
        return None


def _store_build_script_metadata_cache(
    project_path: Path,
    profile: str,
    cache_key: tuple[object, ...],
    native: NativeSection,
) -> None:
    cache_path = _build_script_metadata_cache_path(project_path, profile, cache_key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(f"{cache_path.name}.{uuid4().hex}.tmp")
    try:
        tmp_path.write_text(json.dumps(native.model_dump(mode="json"), sort_keys=True, indent=2), encoding="utf-8")
        tmp_path.replace(cache_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _resolve_build_script_path(manifest: ProjectManifest, project_path: Path) -> Path | None:
    declared = manifest.project.build
    if declared is not None:
        candidate = (project_path / declared).resolve()
        if not candidate.exists():
            raise RuntimeError(f"Declared build script does not exist: {candidate}")
        return candidate

    default_candidate = project_path / "build.enq"
    if default_candidate.exists():
        return default_candidate.resolve()
    return None


def _run_build_script(
    *,
    manifest: ProjectManifest,
    project_path: Path,
    script_path: Path,
    cfg_environment: CfgEnvironment,
    build_ctx: _BuildScriptContext,
) -> NativeSection:
    import toml

    target_dir = project_path / "target" / build_ctx.profile / "build"
    script_workspace = _build_script_workspace_name(
        manifest=manifest,
        project_path=project_path,
        script_path=script_path,
        cfg_environment=cfg_environment,
        build_ctx=build_ctx,
    )
    script_dir = target_dir / "scripts" / script_workspace
    src_dir = script_dir / "src"
    out_dir = target_dir / "out" / script_workspace
    meta_path = out_dir / "build-meta.json"

    src_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    if meta_path.exists():
        meta_path.unlink()

    src_main = src_dir / "main.enq"
    src_main.write_text(script_path.read_text(), encoding="utf-8")

    script_manifest: dict[str, Any] = {
        "project": {
            "name": f"{manifest.project.name}__build_script",
            "target": "executable",
            "version": "0.0.0",
            "description": "",
            "readme": "README.md",
            "licence": "MIT",
            "dependencies": [_rewrite_build_dependency(dep, project_path) for dep in manifest.project.dependencies],
        }
    }
    core_root = _resolve_local_core_root(project_path)
    if manifest.project.name == "core" and core_root is not None:
        runtime_c = (core_root / "runtime.c").resolve()
        if runtime_c.exists():
            script_manifest["native"] = {
                "libraries": [
                    {
                        "name": "encore_core_native_for_build_script",
                        "path": runtime_c.as_posix(),
                    }
                ]
            }
    (script_dir / "encore.toml").write_text(toml.dumps(script_manifest), encoding="utf-8")
    (script_dir / "README.md").write_text("# build script\n", encoding="utf-8")

    _ACTIVE_BUILD_SCRIPTS.add(project_path.resolve())
    try:
        script_compiler = create_compiler(
            script_dir,
            build_ctx.backend,
            build_ctx.profile,
            no_cache=build_ctx.no_cache,
            cfg_overrides=list(build_ctx.cfg_overrides),
            profile_timings=build_ctx.profile_timings,
        )
        _inject_mandatory_core_dependency(script_compiler, script_dir, build_ctx)
        script_ref = _load_refrain(
            script_compiler,
            script_dir,
            type=Refrain.TargetType.EXECUTABLE,
            build_ctx=build_ctx,
        )
        script_outputs = script_compiler.compile_all()
        script_binary = dict(script_outputs)[script_ref.name]

        script_args = [
            meta_path.resolve().as_posix(),
            project_path.resolve().as_posix(),
            script_path.resolve().as_posix(),
            build_ctx.profile,
            build_ctx.backend,
            json.dumps(
                {
                    "flags": sorted(cfg_environment.flags),
                    "values": dict(sorted(cfg_environment.values.items())),
                }
            ),
        ]
        exit_code = run_binary(script_binary, script_args)
        if exit_code != 0:
            raise RuntimeError(f"build.enq failed for '{manifest.project.name}' with exit code {exit_code}")
        if not meta_path.exists():
            raise RuntimeError(
                f"build.enq for '{manifest.project.name}' did not produce build metadata at {meta_path.as_posix()}"
            )

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        native_payload = data.get("native")
        if native_payload is None:
            raise RuntimeError(f"build.enq metadata for '{manifest.project.name}' must include 'native' section")
        if not isinstance(native_payload, dict):
            raise RuntimeError(
                f"build.enq metadata 'native' section must be a table, got: {type(native_payload).__name__}"
            )

        return NativeSection(**native_payload)
    finally:
        _ACTIVE_BUILD_SCRIPTS.discard(project_path.resolve())


def _rewrite_build_dependency(dep: str, project_path: Path) -> str:
    if dep.startswith("path@"):
        target = (project_path / dep.removeprefix("path@")).resolve()
        return f"path@{target.as_posix()}"
    return dep


def _build_script_workspace_name(
    *,
    manifest: ProjectManifest,
    project_path: Path,
    script_path: Path,
    cfg_environment: CfgEnvironment,
    build_ctx: _BuildScriptContext,
) -> str:
    digest = sha1(usedforsecurity=False)
    digest.update(project_path.resolve().as_posix().encode())
    digest.update(script_path.resolve().as_posix().encode())
    digest.update(script_path.read_bytes())
    digest.update(json.dumps(manifest.model_dump(mode="json"), sort_keys=True).encode())
    digest.update(build_ctx.backend.encode())
    digest.update(build_ctx.profile.encode())
    digest.update(",".join(sorted(cfg_environment.flags)).encode())
    digest.update(",".join(f"{k}={v}" for k, v in sorted(cfg_environment.values.items())).encode())
    suffix = f"_{build_ctx.workspace_suffix}" if build_ctx.workspace_suffix else ""
    return f"{manifest.project.name}_{script_path.stem}_{digest.hexdigest()[:12]}{suffix}"


def _resolve_native_path(project_path: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return path.as_posix()
    return (project_path / path).resolve().as_posix()


def _materialize_native_sources(
    native_libraries: list[NativeLibrary],
    project_path: Path,
    profile: str,
) -> list[NativeLibrary]:
    out: list[NativeLibrary] = []
    native_build_dir = project_path / "target" / profile / "build" / "native"
    native_build_dir.mkdir(parents=True, exist_ok=True)

    for native in native_libraries:
        if native.path is None:
            out.append(native)
            continue

        source_path = Path(native.path)
        if source_path.suffix != ".c":
            out.append(native)
            continue

        digest = sha1(str(source_path.resolve()).encode(), usedforsecurity=False).hexdigest()[:16]
        obj_path = native_build_dir / f"{source_path.stem}_{digest}.o"
        try:
            object_is_current = obj_path.exists() and obj_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns
        except OSError:
            object_is_current = False

        if not object_is_current:
            tmp_obj_path = obj_path.with_name(f"{obj_path.name}.{uuid4().hex}.tmp")
            cmd = ["clang", "-std=c11", "-c", str(source_path), "-o", str(tmp_obj_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                tmp_obj_path.unlink(missing_ok=True)
                raise RuntimeError(f"Native source compile error ({source_path}): {result.stderr}")
            tmp_obj_path.replace(obj_path)

        out.append(
            NativeLibrary(
                name=native.name,
                kind=native.kind,
                link_name=native.link_name,
                path=obj_path.as_posix(),
                search_paths=native.search_paths,
                frameworks=native.frameworks,
                link_args=native.link_args,
                cfg=native.cfg,
            )
        )
    return out


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


def build_project(
    cwd: Path,
    backend: str,
    profile: str,
    *,
    no_cache: bool = False,
    cfg_overrides: list[str] | None = None,
    show_status: bool = False,
    profile_timings: bool = False,
) -> list[tuple[str, Path]]:
    build_ctx = _BuildScriptContext(
        backend=backend,
        profile=profile,
        no_cache=no_cache,
        cfg_overrides=tuple(cfg_overrides or []),
        profile_timings=profile_timings,
    )
    compiler = create_compiler(
        cwd,
        backend,
        profile,
        no_cache=no_cache,
        cfg_overrides=cfg_overrides,
        profile_timings=profile_timings,
    )
    _inject_mandatory_core_dependency(compiler, cwd, build_ctx)
    entry_ref = _load_refrain(compiler, cwd, type=resolve_project_target_type(cwd), build_ctx=build_ctx)
    if show_status:
        with _BuildLiveStatus(compiler):
            outputs = compiler.compile_all()
    else:
        outputs = compiler.compile_all()
    outputs_by_name = dict(outputs)
    if profile_timings:
        print_profile_report(compiler)
    return [(entry_ref.name, outputs_by_name[entry_ref.name]), *[(n, p) for n, p in outputs if n != entry_ref.name]]


def run_binary(binary_path: Path, args: list[str], *, env: dict[str, str] | None = None) -> int:
    result = subprocess.run([str(binary_path), *args], check=False, env=env)
    return result.returncode


def update_dependencies(path: Path):
    manifest = load_manifest(path)
    for dependency in manifest.project.dependencies:
        dep_path = _resolve_dependency(dependency, path, update=True)
        dep_manifest = dep_path / ProjectManifest.default_filename()
        if dep_manifest.exists():
            update_dependencies(dep_path)


def sync_dependencies(path: Path, *, update: bool = False, ignore_errors: bool = False) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    visited: set[Path] = set()
    lock_root = path.resolve()

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
                "ref": _resolved_ref_for_lock(dep_ref, project_path, dep_path, lock_root),
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


def _resolved_ref_for_lock(dep_ref: str, project_path: Path, dep_path: Path, lock_root: Path) -> str:
    if dep_ref.startswith("git@"):
        return dep_ref

    if dep_ref.startswith("path@"):
        requested_path = (project_path / dep_ref.removeprefix("path@")).resolve()
        if requested_path == dep_path.resolve():
            return _path_ref_for_lock(lock_root, dep_path)

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

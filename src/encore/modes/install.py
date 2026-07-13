import shutil
import stat
from argparse import Namespace
from pathlib import Path
from typing import Callable

from rich.console import Console

from encore.modes.build import (
    AVAILABLE_BACKENDS,
    AVAILABLE_OPTPROFILES,
    build_project,
)
from encore.utils.manifest import ProjectManifest

INDEX_GITHUB_PREFIX = "git@https://github.com/encore-language-index/"


def add_install_parser(subparsers) -> tuple[str, Callable]:
    section = "install"
    install_parser = subparsers.add_parser(section, help="Build and install an executable project")
    install_parser.add_argument(
        "package",
        nargs="?",
        help="Package reference to install: <name> | git@<repo> | path@<path>. Defaults to current project.",
    )
    install_parser.add_argument("--path", type=str, help="Install executable project from a local path")
    install_parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Install root. Binary is copied to <root>/bin. Defaults to $ENCORE_INSTALL_ROOT or ~/.encore.",
    )
    install_parser.add_argument(
        "--bin-dir",
        type=str,
        default=None,
        help="Install directly into this binary directory. Overrides --root.",
    )
    install_parser.add_argument("--name", type=str, default=None, help="Installed binary name")
    install_parser.add_argument("--force", action="store_true", help="Overwrite an existing installed binary")
    install_parser.add_argument("--update", action="store_true", help="Update git package before installing")
    install_parser.add_argument("--backend", default="llvm", choices=set(AVAILABLE_BACKENDS), help="EHIR backend")
    install_parser.add_argument(
        "--profile",
        default="extreme",
        choices=set(AVAILABLE_OPTPROFILES),
        help="Build optimization profile. Defaults to extreme.",
    )
    install_parser.add_argument("--debug", action="store_true", help="Shortcut for --profile debug")
    install_parser.add_argument("--no-cache", action="store_true", help="Ignore existing EHIR cache for this build")
    install_parser.add_argument(
        "--cfg",
        action="append",
        default=[],
        metavar="PREDICATE",
        help="Add compile-time cfg flag or key=value override.",
    )
    return (section, handle_install)


def handle_install(args: Namespace):
    cwd = Path().resolve()
    console = Console(highlight=False)

    project_path = _resolve_install_project(args, cwd)

    profile = "debug" if args.debug else args.profile
    outputs = build_project(
        project_path,
        args.backend,
        profile,
        no_cache=args.no_cache,
        cfg_overrides=args.cfg,
    )
    _, executable_path = outputs[0]

    manifest = ProjectManifest.read_with_default_filename(project_path)
    installed_name = _validate_binary_name(args.name or manifest.project.name)
    if executable_path.suffix and not installed_name.endswith(executable_path.suffix):
        installed_name += executable_path.suffix

    bin_dir = _resolve_install_bin_dir(args)
    bin_dir.mkdir(parents=True, exist_ok=True)
    destination = bin_dir / installed_name

    if destination.exists() and not args.force:
        raise RuntimeError(f"Installed binary already exists: {destination}. Use --force to overwrite.")

    shutil.copy2(executable_path, destination)
    _ensure_executable(destination)
    console.print(f"Installed {manifest.project.name} -> {destination}")


def _resolve_install_project(args: Namespace, cwd: Path) -> Path:
    if args.path is not None and args.package is not None:
        raise RuntimeError("Use either `encore install <package>` or `encore install --path <path>`, not both")

    if args.path is not None:
        return Path(args.path).expanduser().resolve()

    if args.package is None:
        return cwd

    dep_ref = _normalize_install_ref(args.package)
    raise RuntimeError(f"Package install from indexes is not available in this compiler path yet: {dep_ref}")


def _normalize_install_ref(raw: str) -> str:
    if raw.startswith("git@") or raw.startswith("path@"):
        return raw

    raw_path = Path(raw).expanduser()
    if raw.startswith(".") or raw.startswith("/") or raw.startswith("~"):
        return f"path@{raw_path}"

    return f"{INDEX_GITHUB_PREFIX}{raw}"


def _resolve_install_bin_dir(args: Namespace) -> Path:
    if args.bin_dir is not None:
        return Path(args.bin_dir).expanduser().resolve()

    if args.root is not None:
        return (Path(args.root).expanduser() / "bin").resolve()

    from os import getenv

    env_root = getenv("ENCORE_INSTALL_ROOT")
    if env_root:
        return (Path(env_root).expanduser() / "bin").resolve()

    return (Path.home() / ".encore" / "bin").resolve()


def _validate_binary_name(name: str) -> str:
    if name in {"", ".", ".."}:
        raise RuntimeError(f"Invalid installed binary name: {name!r}")
    if Path(name).name != name:
        raise RuntimeError(f"Installed binary name must not contain path separators: {name!r}")
    return name


def _ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

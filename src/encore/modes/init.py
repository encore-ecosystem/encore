from argparse import Namespace
from pathlib import Path
from typing import Callable

import git
import toml

from encore.utils.manifest import ProjectManifest


def add_init_parser(subparsers) -> tuple[str, Callable]:
    section = "init"
    init_parser = subparsers.add_parser(section, help="Initialize a project")
    init_parser.add_argument("--name", type=str, required=False, help="Overwrite project name")
    return (section, handle_init)


def _create_manifest(root: Path, project_name: str):
    manifest_path = root / ProjectManifest.default_filename()
    if not manifest_path.exists():
        manifest = ProjectManifest.default(project_name)
        with manifest_path.open("w") as f:
            f.write(toml.dumps(manifest.model_dump()))


def _create_src(root: Path):
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.enq").touch(exist_ok=True)


def _initialize_git_repo(root: Path):
    if not (root / ".git").exists():
        git.Repo.init(root)

    (root / "README.md").touch(exist_ok=True)

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        with (root / ".gitignore").open("w") as f:
            f.write("target\n")


def handle_init(args: Namespace):
    cwd = Path().resolve()

    _create_manifest(cwd, args.name or cwd.name)
    _create_src(cwd)
    _initialize_git_repo(cwd)

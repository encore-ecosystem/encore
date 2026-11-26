#!/usr/bin/env python3
"""Export pinned Git sources and identify the exact SDK used by native CI."""

import argparse
import configparser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tomllib

PACKAGES = (
    "core", "platform", "std", "rich", "serialize", "json", "binary", "log",
    "profile", "ehir-core", "ehir", "ehir-llvm-backend", "toml",
    "llvm", "argparse", "secret-store",
)
ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def links(root: Path, ref: str) -> dict[str, str]:
    result = {}
    for entry in git(root, "ls-tree", "-r", "-z", ref).split(b"\0"):
        if entry:
            header, name = entry.split(b"\t", 1)
            mode, kind, commit = header.split()
            if mode == b"160000" and kind == b"commit":
                result[os.fsdecode(name)] = commit.decode("ascii")
    return result


def module_urls(root: Path, ref: str) -> dict[str, str]:
    if not links(root, ref):
        return {}
    config = configparser.RawConfigParser()
    config.read_string(git(root, "show", f"{ref}:.gitmodules").decode("utf-8"))
    result = {}
    for section in config.sections():
        path = config.get(section, "path")
        if path in result:
            raise ValueError(f"duplicate submodule path: {path}")
        result[path] = config.get(section, "url")
    return result


def repository_for_link(root: Path, path: str, commit: str) -> Path:
    repository = root / path
    try:
        actual = Path(os.fsdecode(git(repository, "rev-parse", "--show-toplevel")).strip()).resolve()
        if actual != repository.resolve():
            raise ValueError("not an initialized submodule")
        git(repository, "cat-file", "-e", f"{commit}^{{commit}}")
    except (OSError, ValueError) as error:
        raise ValueError(f"SDK submodule {path} at {commit} is unavailable; run "
                         "git submodule update --init --recursive") from error
    return repository


def _child_paths(path: str, selected: tuple[str, ...]) -> tuple[str, ...] | None:
    if not selected:
        return ()
    children = []
    for item in selected:
        if path == item or path.startswith(item.rstrip("/") + "/"):
            return ()
        if item.startswith(path + "/"):
            children.append(item[len(path) + 1:])
    return tuple(children) if children else None


def export_tree(root: Path, ref: str, destination: Path, paths: tuple[str, ...] = ()) -> None:
    """Materialize a commit, expanding gitlinks at their recorded commits."""
    destination.mkdir(parents=True, exist_ok=True)
    pinned = links(root, ref)
    command = ["-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar", ref]
    if paths:
        parent_paths = []
        for selected in paths:
            parent_paths.append(next((path for path in pinned if selected.startswith(path + "/")), selected))
        command.extend(["--", *sorted(set(parent_paths))])
    archive = git(root, *command)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(destination, filter="data")
    for path, commit in pinned.items():
        selected = _child_paths(path, paths)
        if selected is None:
            continue
        child = repository_for_link(root, path, commit)
        export_tree(child, commit, destination / path, selected)


def export_package(root: Path, ref: str, folder: str, destination: Path) -> None:
    if folder not in PACKAGES:
        raise ValueError(f"unknown SDK package: {folder}")
    path = f"packages/{folder}"
    pinned = links(root, ref).get(path)
    if pinned:
        export_tree(repository_for_link(root, path, pinned), pinned, destination)
    else:
        # Releases predating submodules keep ordinary package directories.
        export_tree(root, f"{ref}:{path}", destination)


def sdk_manifest(root: Path, ref: str = "HEAD", verify_checkout: bool = False,
                 packages: tuple[str, ...] = PACKAGES) -> dict:
    pinned = links(root, ref)
    urls = module_urls(root, ref)
    rows = []
    for folder in packages:
        path = f"packages/{folder}"
        if path not in pinned or path not in urls:
            raise ValueError(f"expected a pinned SDK submodule: {path}")
        commit = pinned[path]
        repository = repository_for_link(root, path, commit)
        manifest = tomllib.loads(git(repository, "show", f"{commit}:encore.toml").decode("utf-8"))["project"]
        if verify_checkout:
            actual = git(repository, "rev-parse", "HEAD").decode("ascii").strip()
            if actual != commit:
                raise ValueError(f"SDK checkout differs from the gitlink: {path}: {actual} != {commit}")
            if git(repository, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError(f"SDK package has tracked changes: {path}")
        rows.append({"path": path, "repository": urls[path], "commit": commit,
                     "name": manifest["name"], "version": manifest["version"]})
    if set(pinned) != {f"packages/{folder}" for folder in packages}:
        raise ValueError("unexpected or missing SDK submodule in the parent tree")
    return {"schema": 1, "packages": rows}


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def verify_provenance(root: Path, provenance: dict, ref: str = "HEAD") -> None:
    expected = sdk_manifest(root, ref, verify_checkout=True)
    if provenance.get("sdk_packages") != expected["packages"] or provenance.get("sdk_sha256") != manifest_digest(expected):
        raise ValueError("build provenance belongs to a different SDK snapshot")


def working_tree_files(root: Path) -> list[str]:
    """Include edited and untracked inputs inside submodules for benchmarks."""
    names = os.fsdecode(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")).split("\0")
    out = {name for name in names if name and (root / name).is_file()}
    for path, commit in links(root, "HEAD").items():
        child = repository_for_link(root, path, commit)
        out.update(f"{path}/{name}" for name in working_tree_files(child))
    return sorted(out)


def copy_working_tree(root: Path, destination: Path) -> list[str]:
    names = working_tree_files(root)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    return names


def check_sdk_archive(archive: Path, prefix: str, manifest: dict, root: Path | None = None, ref: str = "HEAD") -> None:
    import zipfile
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as stream:
            members = stream.namelist()
            files = {name: stream.read(name) for name in members if not name.endswith("/")}
    else:
        with tarfile.open(archive, "r:gz") as stream:
            members = stream.getnames()
            files = {item.name: stream.extractfile(item).read() for item in stream.getmembers() if item.isfile()}
    if any(".git" in PurePosixPath(name).parts for name in members):
        raise ValueError("Git metadata was included in the distribution")
    bundled = json.loads(files[f"{prefix}/SDK.json"])
    if bundled != manifest:
        raise ValueError("bundled SDK manifest differs from the build snapshot")
    if root is not None and sdk_manifest(root, ref, verify_checkout=True) != manifest:
        raise ValueError("archive manifest differs from the pinned SDK")
    for package in manifest["packages"]:
        folder = PurePosixPath(package["path"]).name
        path = f"{prefix}/lib/encore/index/{folder}/encore.toml"
        project = tomllib.loads(files[path].decode("utf-8"))["project"]
        if project["name"] != package["name"] or project["version"] != package["version"]:
            raise ValueError(f"bundled package identity differs: {folder}")
        if root is not None:
            repository = repository_for_link(root, package["path"], package["commit"])
            with tarfile.open(fileobj=io.BytesIO(git(repository, "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar", package["commit"]))) as source:
                expected = {item.name: source.extractfile(item).read() for item in source.getmembers() if item.isfile()}
            package_prefix = f"{prefix}/lib/encore/index/{folder}/"
            actual = {name[len(package_prefix):]: data for name, data in files.items() if name.startswith(package_prefix)}
            if actual != expected:
                raise ValueError(f"bundled package files differ from the pinned commit: {folder}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export")
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--path", action="append", default=[])
    package = actions.add_parser("export-package")
    package.add_argument("--package", choices=PACKAGES, required=True)
    package.add_argument("--destination", type=Path, required=True)
    sdk = actions.add_parser("export-sdk")
    sdk.add_argument("--destination", type=Path, required=True)
    sdk.add_argument("--manifest", type=Path, required=True)
    manifest = actions.add_parser("manifest")
    manifest.add_argument("--verify-checkout", action="store_true")
    manifest.add_argument("--output", type=Path)
    provenance = actions.add_parser("verify-provenance")
    provenance.add_argument("provenance", type=Path)
    archive = actions.add_parser("verify-archive")
    archive.add_argument("archive", type=Path)
    archive.add_argument("--prefix", required=True)
    archive.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.action == "export":
            export_tree(root, args.ref, args.destination, tuple(args.path))
        elif args.action == "export-package":
            export_package(root, args.ref, args.package, args.destination)
        elif args.action == "export-sdk":
            value = sdk_manifest(root, args.ref, verify_checkout=True)
            for folder in PACKAGES:
                export_package(root, args.ref, folder, args.destination / folder)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_bytes(manifest_bytes(value))
        elif args.action == "manifest":
            content = manifest_bytes(sdk_manifest(root, args.ref, args.verify_checkout))
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(content)
            else:
                sys.stdout.buffer.write(content)
        elif args.action == "verify-provenance":
            verify_provenance(root, json.loads(args.provenance.read_bytes()), args.ref)
        elif args.action == "verify-archive":
            check_sdk_archive(args.archive, args.prefix, json.loads(args.manifest.read_bytes()), root, args.ref)
    except (OSError, ValueError, KeyError, tarfile.TarError, configparser.Error) as error:
        print(f"sdk-packages: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

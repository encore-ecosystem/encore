#!/usr/bin/env python3
"""Read the compiler release identity without requiring a built compiler."""

import argparse
import json
from pathlib import Path
import re
import sys
import tomllib


MINIMUM_SEED = (0, 1, 9)


def metadata(root: Path) -> dict[str, str]:
    with (root / "encore.toml").open("rb") as source:
        project = tomllib.load(source)["project"]
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("[project].name must be a nonempty string")
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("[project].version must be a three-component compatibility version")
    identity = (root / "src/version.enq").read_text(encoding="utf-8")
    names = re.findall(
        r'^pub fn compiler_release_name\(\) -> str \{\s*ret "([a-z][a-z0-9-]*)"\s*\}',
        identity, re.MULTILINE,
    )
    if len(names) != 1:
        raise ValueError("compiler_release_name() must return one lowercase release-name literal")
    return {"name": name, "version": version, "release_name": names[0],
            "release": f"{version}-{names[0]}"}


def check_seed(tag: str) -> None:
    match = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)(?:-[a-z][a-z0-9-]*)?", tag)
    if not match or tuple(map(int, match.groups())) < MINIMUM_SEED:
        raise ValueError("bootstrapping requires published Encore 0.1.9 or newer (project constants)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--field", choices=("name", "version", "release_name", "release"))
    action.add_argument("--check-seed", metavar="TAG")
    args = parser.parse_args()
    try:
        if args.check_seed is not None:
            check_seed(args.check_seed)
            return 0
        values = metadata(args.root)
        print(values[args.field] if args.field else json.dumps(values, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"project-metadata: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

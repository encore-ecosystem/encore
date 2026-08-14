#!/usr/bin/env python3
"""Check that enbook covers the language guide and every core/std module."""

from __future__ import annotations

import re
import sys
from pathlib import Path


FEATURE_PAGES = (
    "comments-and-docs",
    "imports-and-visibility",
    "bindings-and-static",
    "literals",
    "strings-and-fstrings",
    "format-macro",
    "collections",
    "operators-and-casts",
    "functions-and-generics",
    "attributes-and-cfg",
    "decorators",
    "closures",
    "structs-and-placement",
    "methods",
    "enums-and-match",
    "traits-and-dyn",
    "conditionals",
    "loops-and-ranges",
    "context-managers",
    "result-and-try",
    "async-await",
    "spawn-and-join",
    "macros",
    "unsafe-and-ehir",
)

INCLUDE = re.compile(r"\{\{#include\s+([^}:]+)(?::([^}]+))?\}\}")


def modules(source: Path) -> set[str]:
    return {path.parent.name for path in source.glob("*/mod.enq")}


def check_page(source: Path, summary: str, relative: str, errors: list[str]) -> None:
    page = source / relative
    if not page.is_file():
        errors.append(f"missing page: {relative}")
        return
    if f"({relative})" not in summary:
        errors.append(f"page absent from SUMMARY.md: {relative}")
    text = page.read_text(encoding="utf-8")
    includes = list(INCLUDE.finditer(text))
    if not includes:
        errors.append(f"page has no source-backed example: {relative}")
    for include in includes:
        included = (page.parent / include.group(1)).resolve()
        if not included.is_file():
            errors.append(f"broken include in {relative}: {include.group(1)}")
            continue
        anchor = include.group(2)
        if anchor:
            included_text = included.read_text(encoding="utf-8")
            if f"// ANCHOR: {anchor}" not in included_text or (
                f"// ANCHOR_END: {anchor}" not in included_text
            ):
                errors.append(f"missing anchor {anchor!r} for {relative}")


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    source = repository / "docs" / "enbook-en" / "src"
    index = repository.parent / "encore-index" / "packages"
    summary = (source / "SUMMARY.md").read_text(encoding="utf-8")
    errors: list[str] = []

    for feature in FEATURE_PAGES:
        check_page(source, summary, f"features/{feature}.md", errors)
    for package in ("core", "std"):
        exported_modules = modules(index / package / "src")
        documented_modules = {
            path.stem for path in (source / "library" / package).glob("*.md")
        }
        missing = sorted(exported_modules - documented_modules)
        unexpected = sorted(documented_modules - exported_modules)
        if missing:
            errors.append(f"{package} modules without pages: {', '.join(missing)}")
        if unexpected:
            errors.append(f"{package} pages without modules: {', '.join(unexpected)}")
        for module in sorted(exported_modules):
            check_page(source, summary, f"library/{package}/{module}.md", errors)

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"enbook coverage passed: {len(FEATURE_PAGES)} features, "
        f"{len(modules(index / 'core' / 'src'))} core modules, "
        f"{len(modules(index / 'std' / 'src'))} std modules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

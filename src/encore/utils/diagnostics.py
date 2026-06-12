from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CompileDiagnostic(Exception):
    message: str
    stage: str | None = None
    module_id: Path | None = None
    line: int | None = None
    column: int | None = None
    span_length: int | None = None
    source_line: str | None = None
    cause: Exception | None = None

    def __str__(self) -> str:
        return self.message


def with_diagnostic_context(
    exc: Exception,
    *,
    stage: str | None = None,
    module_id: Path | None = None,
    source_text: str | None = None,
) -> CompileDiagnostic:
    if isinstance(exc, CompileDiagnostic):
        if exc.stage is None:
            exc.stage = stage
        if exc.module_id is None:
            exc.module_id = module_id
        if exc.source_line is None and source_text is not None and exc.line is not None:
            exc.source_line = _line_from_source(source_text, exc.line)
        return exc

    return CompileDiagnostic(
        message=str(exc),
        stage=stage,
        module_id=module_id if module_id is not None else getattr(exc, "module_id", None),
        line=getattr(exc, "line", None),
        column=getattr(exc, "column", None),
        span_length=getattr(exc, "span_length", None),
        source_line=getattr(exc, "source_line", None),
        cause=exc,
    )


def render_diagnostic(exc: Exception) -> str:
    diag = exc if isinstance(exc, CompileDiagnostic) else CompileDiagnostic(message=str(exc), cause=exc)
    red = "\x1b[1;31m"
    yellow = "\x1b[1;33m"
    cyan = "\x1b[1;36m"
    dim = "\x1b[2m"
    reset = "\x1b[0m"
    lines: list[str] = []
    lines.append(f"{red}Error:{reset} {diag.message}")

    if diag.stage is not None:
        lines.append(f"{yellow}Stage:{reset} {diag.stage}")

    if diag.module_id is not None:
        if diag.line is not None and diag.column is not None:
            lines.append(f"{cyan} --> {diag.module_id}:{diag.line + 1}:{diag.column + 1}{reset}")
        elif diag.line is not None:
            lines.append(f"{cyan} --> {diag.module_id}:{diag.line + 1}{reset}")
        else:
            lines.append(f"{cyan} --> {diag.module_id}{reset}")

    if diag.source_line is not None:
        if diag.line is not None:
            line_no = str(diag.line + 1)
            rendered_source = diag.source_line
            if diag.column is not None:
                span_length = max(diag.span_length or 1, 1)
                start = max(diag.column, 0)
                end = min(start + span_length, len(rendered_source))
                rendered_source = (
                    rendered_source[:start]
                    + red
                    + rendered_source[start:end]
                    + reset
                    + rendered_source[end:]
                )
            lines.append(f"{dim}{line_no:>4} |{reset} {rendered_source}")
            if diag.column is not None:
                caret_pad = " " * max(diag.column, 0)
                carets = "^" * max(diag.span_length or 1, 1)
                lines.append(f"{dim}     |{reset} {caret_pad}{red}{carets}{reset}")
        else:
            lines.append(f"      {diag.source_line}")

    return "\n".join(lines)


def _line_from_source(source_text: str | None, line: Optional[int]) -> str | None:
    if source_text is None:
        return None
    if line is None:
        return None
    rows = source_text.splitlines()
    if line < 0 or line >= len(rows):
        return None
    return rows[line]

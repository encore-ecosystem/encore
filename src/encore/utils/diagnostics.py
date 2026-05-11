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
        module_id=module_id,
        source_line=None,
        cause=exc,
    )


def render_diagnostic(exc: Exception) -> str:
    diag = exc if isinstance(exc, CompileDiagnostic) else CompileDiagnostic(message=str(exc), cause=exc)
    lines: list[str] = []
    lines.append(f"Error: {diag.message}")

    if diag.stage is not None:
        lines.append(f"Stage: {diag.stage}")

    if diag.module_id is not None:
        if diag.line is not None and diag.column is not None:
            lines.append(f" --> {diag.module_id}:{diag.line + 1}:{diag.column + 1}")
        elif diag.line is not None:
            lines.append(f" --> {diag.module_id}:{diag.line + 1}")
        else:
            lines.append(f" --> {diag.module_id}")

    if diag.source_line is not None:
        if diag.line is not None:
            line_no = str(diag.line + 1)
            lines.append(f"{line_no:>4} | {diag.source_line}")
            if diag.column is not None:
                caret_pad = " " * max(diag.column, 0)
                lines.append(f"     | {caret_pad}^")
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

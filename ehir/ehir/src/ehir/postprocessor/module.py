from dataclasses import dataclass
from pathlib import Path

from .derectives import (
    ProcessedDerective_extern_fn,
    ProcessedDerective_fn,
    ProcessedDerective_struct,
)


@dataclass
class ProcessedModule:
    id: Path
    structs: list[ProcessedDerective_struct]
    funcs: list[ProcessedDerective_extern_fn | ProcessedDerective_fn]

    def __str__(self) -> str:
        return "\n\n".join(map(str, [*self.structs, *self.funcs]))

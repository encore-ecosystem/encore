from dataclasses import dataclass
from pathlib import Path

from ehir.builder import EHIR_Module

from .derectives import (
    ProcessedDerective_extern_fn,
    ProcessedDerective_fn,
    ProcessedDerective_struct,
)


@dataclass(init=False)
class EHIR_ProcessedModule(EHIR_Module):
    structs: list[ProcessedDerective_struct]
    funcs: list[ProcessedDerective_extern_fn | ProcessedDerective_fn]

    def __init__(
        self,
        id: Path,
        structs: list[ProcessedDerective_struct],
        funcs: list[ProcessedDerective_extern_fn | ProcessedDerective_fn],
    ):
        super().__init__(ast=[], id=id)
        self.structs = structs
        self.funcs = funcs

    def __str__(self) -> str:
        return "\n\n".join(map(str, [*self.structs, *self.funcs]))

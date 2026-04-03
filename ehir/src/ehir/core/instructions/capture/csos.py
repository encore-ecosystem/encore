from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.struct import Struct


@dataclass
class Instruction_csos(Assignable):
    struct: Struct

    def __str__(self) -> str:
        return f"{super().__str__()}csos {self.struct}"

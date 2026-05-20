from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.struct import Struct


@dataclass
class Instruction_scstruct(Assignable):
    struct: Struct

    def __str__(self) -> str:
        return f"{super().__str__()}scstruct {self.struct}"

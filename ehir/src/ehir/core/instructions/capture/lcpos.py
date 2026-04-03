from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.primitives.base import Primitive


@dataclass
class Instruction_lcpos(Assignable):
    primitive: Primitive

    def __str__(self) -> str:
        return f"{super().__str__()}lcpos {self.primitive}"

from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.primitives.base import Primitive


@dataclass
class Instruction_scpos(Assignable):
    primitive: Primitive

    def __str__(self) -> str:
        return f"{super().__str__()}scpos {self.primitive}"

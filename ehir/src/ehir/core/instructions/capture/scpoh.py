from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.primitives.base import Primitive


@dataclass
class Instruction_scpoh(Assignable):
    primitive: Primitive

    def __str__(self) -> str:
        return f"{super().__str__()}scpoh {self.primitive}"

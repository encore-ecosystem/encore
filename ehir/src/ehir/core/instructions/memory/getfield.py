from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class Instruction_getfield(Assignable):
    src: Variable
    field: Variable

    def __str__(self) -> str:
        return f"{super().__str__()}getfield {self.src}, {self.field}"

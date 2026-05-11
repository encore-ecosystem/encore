from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class Instruction_wrap(Assignable):
    variable: Variable

    def __str__(self) -> str:
        return f"{super().__str__()}wrap {self.variable}"

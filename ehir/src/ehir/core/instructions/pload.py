from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class Instruction_pload(Assignable):
    var: Variable

    def __str__(self) -> str:
        return f"{super().__str__()}pload {self.var}"

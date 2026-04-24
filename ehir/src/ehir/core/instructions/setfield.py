from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.variable import Variable


@dataclass
class Instruction_setfield(Instruction):
    var: Variable
    field: Variable
    value: Variable

    def __str__(self) -> str:
        return f"setfield {self.var}, {self.field}, {self.value}"

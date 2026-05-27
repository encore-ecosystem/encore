from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.variable import Variable


@dataclass
class Instruction_drop(Instruction):
    var: Variable

    def __str__(self) -> str:
        return f"drop {self.var}"

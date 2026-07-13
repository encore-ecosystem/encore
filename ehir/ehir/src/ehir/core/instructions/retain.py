from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.variable import Variable


@dataclass
class Instruction_retain(Instruction):
    var: Variable

    def __str__(self) -> str:
        return f"retain {self.var}"

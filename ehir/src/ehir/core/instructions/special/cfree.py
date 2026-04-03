from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.type import SmartPointer
from ehir.core.variable import Variable


@dataclass
class Instruction_cfree(Instruction):
    var: Variable

    def __post_init__(self):
        assert self.var.type
        assert isinstance(self.var.type, SmartPointer)

    def __str__(self) -> str:
        return f"cfree {self.var}"

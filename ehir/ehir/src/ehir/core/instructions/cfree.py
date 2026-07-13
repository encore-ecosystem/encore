from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.type import is_box_type
from ehir.core.variable import Variable


@dataclass
class Instruction_cfree(Instruction):
    var: Variable

    def __post_init__(self):
        assert self.var.type
        assert is_box_type(self.var.type)

    def __str__(self) -> str:
        return f"cfree {self.var}"

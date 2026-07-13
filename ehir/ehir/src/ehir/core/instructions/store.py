from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.variable import Variable


@dataclass
class Instruction_store(Instruction):
    var_src: Variable
    var_dst: Variable

    def __str__(self) -> str:
        return f"store {self.var_src}, {self.var_dst}"

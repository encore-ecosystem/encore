from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class Instruction_hrealloc(Assignable):
    var: Variable
    count: Variable

    def __str__(self) -> str:
        return f"{super().__str__()}hrealloc {self.var}, {self.count}"

from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.primitives.base import PrimitiveType
from ehir.core.variable import Variable


@dataclass
class Instruction_pcast(Assignable):
    var: Variable
    type: PrimitiveType

    def __str__(self) -> str:
        return f"{super().__str__()}pcast {self.var}, {self.type}"

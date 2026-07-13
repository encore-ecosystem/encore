from dataclasses import dataclass

from ehir.core.instructions.base import Instruction
from ehir.core.primitives.base import Primitive
from ehir.core.variable import Variable


@dataclass
class Instruction_put(Instruction):
    primitive: Primitive
    var: Variable

    def __str__(self) -> str:
        return f"put {self.primitive}, {self.var}"

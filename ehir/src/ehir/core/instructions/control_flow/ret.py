from dataclasses import dataclass

from ehir.core.variable import Variable

from .base import ControlFlow


@dataclass
class Instruction_ret(ControlFlow):
    var: Variable

    def __str__(self) -> str:
        return f"ret {self.var}"

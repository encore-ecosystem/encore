from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.type import Type
from ehir.core.variable import Variable


@dataclass
class Instruction_call(Assignable):
    fn_name: str
    generics: list[Type]
    args: list[Variable]
    is_unsafe: bool = False

    def __str__(self) -> str:
        generics_repr = ("[" + ", ".join(str(x) for x in self.generics) + "]") if self.generics else ""
        unsafe_repr = "unsafe " if self.is_unsafe else ""
        return f"{super().__str__()}{unsafe_repr}call {generics_repr}{self.fn_name}({', '.join(str(arg) for arg in self.args)})"

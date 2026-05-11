from dataclasses import dataclass

from ehir.core.variable import Variable


@dataclass
class Instruction:
    pass


@dataclass
class Assignable(Instruction):
    var_out: Variable

    def __str__(self) -> str:
        return f"{self.var_out} = "

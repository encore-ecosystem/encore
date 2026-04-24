from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.variable import Variable


@dataclass
class PhiPair:
    var: Variable
    block_label: str


@dataclass
class Instruction_phi(Assignable):
    args: list[PhiPair]

    def __str__(self) -> str:
        return f"{super().__str__()}phi {', '.join(f'{arg.var} ${arg.block_label}' for arg in self.args)}"

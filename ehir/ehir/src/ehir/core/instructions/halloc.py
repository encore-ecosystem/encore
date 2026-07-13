from dataclasses import dataclass

from ehir.core.instructions.base import Assignable
from ehir.core.type import Type


@dataclass
class Instruction_halloc(Assignable):
    type: Type

    def __str__(self) -> str:
        return f"{super().__str__()}halloc {self.type}"

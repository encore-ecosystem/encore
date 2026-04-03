from dataclasses import dataclass

from ehir.core.enum import Enum
from ehir.core.instructions.base import Assignable


@dataclass
class Instruction_ceos(Assignable):
    enum: Enum

    def __str__(self) -> str:
        return f"{super().__str__()}ceos {self.enum}"
